import numpy as np
from gnuradio import gr
import time
import socket
import struct
import math


class doppler_velocity(gr.sync_block):

    """
    Multi-target CW Doppler detector.

    Processing:
        Input
          -> 8192-point FFT
          -> Doppler search window
          -> CA-CFAR
          -> local peak detection
          -> peak grouping
          -> velocity estimation

    UDP:
        Sends one 12-byte packet per detected target:

            float32 doppler_hz
            float32 velocity_mps
            float32 power_db

        The packet format is intentionally kept identical to the
        original single-target block so existing UDP receivers can
        continue to decode each target.
    """

    def __init__(
        self,
        samp_rate=48000,
        fft_size=8192,
        center_freq_hz=5.5e9,
        print_every_n=5,
        noise_thresh_db=10.0,
        tone_offset_hz=500.0,
        max_velocity_mps=5.0,
        udp_ip="127.0.0.1",
        udp_port=5005,
        max_targets=10
    ):

        gr.sync_block.__init__(
            self,
            name="doppler_velocity",
            in_sig=[np.complex64],
            out_sig=None
        )

        # -----------------------------
        # Radar parameters
        # -----------------------------
        self.samp_rate = float(samp_rate)
        self.fft_size = int(fft_size)

        self.c = 3e8
        self.center_freq_hz = float(center_freq_hz)
        self.wavelength = self.c / self.center_freq_hz

        self.tone_offset = float(tone_offset_hz)
        self.max_velocity = float(max_velocity_mps)

        # Existing threshold retained as an additional minimum SNR gate
        self.threshold = float(noise_thresh_db)

        self.bin_resolution = self.samp_rate / self.fft_size

        # -----------------------------
        # Multi-target CFAR settings
        # -----------------------------

        # Number of training cells on each side
        self.training_cells = 24

        # Guard cells on each side
        self.guard_cells = 4

        # Desired probability of false alarm
        self.pfa = 1e-5

        # Minimum separation between reported peaks
        self.min_peak_separation_bins = 5

        # Maximum number of targets
        self.max_targets = int(max_targets)

        # -----------------------------
        # FFT window
        # -----------------------------
        self.window = np.hanning(self.fft_size)

        # -----------------------------
        # Input buffer
        # -----------------------------
        self.buffer = np.zeros(
            self.fft_size,
            dtype=np.complex64
        )

        self.buf_idx = 0
        self.call_count = 0

        # -----------------------------
        # Last detection
        # -----------------------------
        self.last_detections = []

        self.last_print = time.time()

        # -----------------------------
        # UDP
        # -----------------------------
        self.udp_ip = udp_ip
        self.udp_port = int(udp_port)

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

    # ==========================================================
    # GNU Radio work()
    # ==========================================================

    def work(self, input_items, output_items):

        samples = input_items[0]

        for sample in samples:

            self.buffer[self.buf_idx] = sample
            self.buf_idx += 1

            if self.buf_idx >= self.fft_size:

                self.process_block(self.buffer)

                self.buf_idx = 0

        return len(samples)

    # ==========================================================
    # Main FFT / CFAR processing
    # ==========================================================

    def process_block(self, block):

        # ------------------------------------------
        # Window + FFT
        # ------------------------------------------

        windowed = block * self.window

        spectrum = np.fft.fftshift(
            np.fft.fft(windowed)
        )

        magnitude = np.abs(spectrum)

        # Power spectrum
        power = magnitude ** 2

        # dB spectrum for reporting
        mag_db = 20 * np.log10(
            magnitude + 1e-12
        )

        center = self.fft_size // 2

        # ------------------------------------------
        # Doppler search region
        # ------------------------------------------

        max_doppler_hz = (
            2.0 *
            self.max_velocity /
            self.wavelength
        )

        max_doppler_bins = int(
            np.ceil(
                max_doppler_hz /
                self.bin_resolution
            )
        )

        tone_bin = (
            center +
            int(
                round(
                    self.tone_offset /
                    self.bin_resolution
                )
            )
        )

        lo = max(
            self.training_cells +
            self.guard_cells,
            tone_bin - max_doppler_bins
        )

        hi = min(
            self.fft_size -
            self.training_cells -
            self.guard_cells -
            1,
            tone_bin + max_doppler_bins
        )

        if hi <= lo:
            return

        # ------------------------------------------
        # CA-CFAR
        # ------------------------------------------

        candidate_bins = []

        # CA-CFAR scaling factor
        #
        # alpha = N * (Pfa^(-1/N) - 1)
        #
        # N = number of training cells
        #
        n_training = 2 * self.training_cells

        alpha = (
            n_training *
            (
                self.pfa **
                (-1.0 / n_training)
                - 1.0
            )
        )

        for k in range(lo, hi + 1):

            # Training cells
            left_start = (
                k -
                self.guard_cells -
                self.training_cells
            )

            left_end = (
                k -
                self.guard_cells
            )

            right_start = (
                k +
                self.guard_cells +
                1
            )

            right_end = (
                k +
                self.guard_cells +
                self.training_cells +
                1
            )

            left_training = power[
                left_start:left_end
            ]

            right_training = power[
                right_start:right_end
            ]

            training = np.concatenate(
                (
                    left_training,
                    right_training
                )
            )

            if len(training) == 0:
                continue

            noise_power = np.mean(training)

            threshold_power = (
                alpha *
                noise_power
            )

            cell_power = power[k]

            # CFAR detection
            if cell_power > threshold_power:

                # Additional SNR-style check
                noise_db = 10 * np.log10(
                    noise_power + 1e-20
                )

                signal_db = mag_db[k]

                snr_db = (
                    signal_db -
                    10 * np.log10(
                        noise_power + 1e-20
                    )
                )

                if snr_db >= self.threshold:

                    # Local maximum test
                    if (
                        power[k] >=
                        power[k - 1]
                        and
                        power[k] >=
                        power[k + 1]
                    ):

                        candidate_bins.append(
                            k
                        )

        # ------------------------------------------
        # No targets
        # ------------------------------------------

        if len(candidate_bins) == 0:

            self.last_detections = []

            return

        # ------------------------------------------
        # Sort strongest targets first
        # ------------------------------------------

        candidate_bins.sort(
            key=lambda x: power[x],
            reverse=True
        )

        # ------------------------------------------
        # Peak grouping / suppression
        # ------------------------------------------

        selected_bins = []

        for candidate in candidate_bins:

            too_close = False

            for selected in selected_bins:

                if abs(
                    candidate -
                    selected
                ) <= self.min_peak_separation_bins:

                    too_close = True
                    break

            if not too_close:

                selected_bins.append(
                    candidate
                )

            if len(selected_bins) >= self.max_targets:
                break

        # ------------------------------------------
        # Convert bins → Doppler → velocity
        # ------------------------------------------

        detections = []

        for peak_bin in selected_bins:

            # --------------------------------------
            # Parabolic interpolation
            # --------------------------------------

            peak = float(peak_bin)

            if (
                1 <= peak_bin <
                self.fft_size - 1
            ):

                a = mag_db[
                    peak_bin - 1
                ]

                b = mag_db[
                    peak_bin
                ]

                c = mag_db[
                    peak_bin + 1
                ]

                denom = (
                    a -
                    2.0 * b +
                    c
                )

                if abs(denom) > 1e-12:

                    peak += (
                        0.5 *
                        (a - c) /
                        denom
                    )

            # --------------------------------------
            # FFT frequency
            # --------------------------------------

            raw_freq = (
                peak - center
            ) * self.bin_resolution

            # Remove the artificial tone offset
            doppler_freq = (
                raw_freq -
                self.tone_offset
            )

            # --------------------------------------
            # Doppler → velocity
            # --------------------------------------

            velocity = (
                doppler_freq *
                self.wavelength /
                2.0
            )

            power_db = float(
                mag_db[peak_bin]
            )

            detections.append(
                (
                    float(doppler_freq),
                    float(velocity),
                    power_db
                )
            )

        # ------------------------------------------
        # Sort targets by velocity
        # ------------------------------------------

        detections.sort(
            key=lambda x: x[1]
        )

        self.last_detections = detections

        self.call_count += 1

        # ------------------------------------------
        # UDP output
        # ------------------------------------------
        #
        # One packet per target.
        #
        # Existing receiver can continue reading:
        #
        #     doppler
        #     velocity
        #     dBFS
        #
        # Each packet represents one target.
        # ------------------------------------------

        for doppler_freq, velocity, power_db in detections:

            packet = struct.pack(
                "<fff",
                doppler_freq,
                velocity,
                power_db
            )

            try:

                self.sock.sendto(
                    packet,
                    (
                        self.udp_ip,
                        self.udp_port
                    )
                )

            except OSError as e:

                print(
                    f"UDP send failed: {e}"
                )

        # ------------------------------------------
        # Console display
        # ------------------------------------------

        if time.time() - self.last_print >= 1.0:

            print(
                "\n"
                "========================================\n"
                "         MULTI-TARGET DOPPLER\n"
                "========================================"
            )

            if len(detections) == 0:

                print(
                    "No targets detected"
                )

            else:

                print(
                    f"Targets detected: "
                    f"{len(detections)}"
                )

                for i, (
                    doppler,
                    velocity,
                    power_db
                ) in enumerate(
                    detections,
                    start=1
                ):

                    print(
                        f"Target {i}: "
                        f"Doppler = "
                        f"{doppler:+.2f} Hz | "
                        f"Velocity = "
                        f"{velocity:+.3f} m/s | "
                        f"Power = "
                        f"{power_db:.1f} dB"
                    )

            print(
                "========================================"
            )

            self.last_print = time.time()
