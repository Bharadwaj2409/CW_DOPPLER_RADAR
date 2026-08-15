import numpy as np
from gnuradio import gr
import time
import socket
import struct


class doppler_velocity(gr.sync_block):
    """
    Doppler Velocity Estimator with direct UDP output.
    Sends [doppler, velocity, dBFS] as a 12-byte UDP packet
    directly, bypassing UDP Sink entirely.
    """

    def __init__(self,
                 samp_rate=48000,
                 fft_size=8192,
                 center_freq_hz=5.5e9,
                 print_every_n=5,
                 noise_thresh_db=10.0,
                 tone_offset_hz=500.0,
                 max_velocity_mps=10.0,
                 udp_ip="127.0.0.1",
                 udp_port=5005):

        gr.sync_block.__init__(
            self,
            name="doppler_velocity",
            in_sig=[np.complex64],
            out_sig=None   # no stream output needed anymore
        )

        self.samp_rate = samp_rate
        self.fft_size = fft_size

        self.c = 3e8
        self.wavelength = self.c / center_freq_hz

        self.threshold = noise_thresh_db
        self.print_every_n = print_every_n
        self.tone_offset = tone_offset_hz
        self.max_velocity = max_velocity_mps

        self.bin_resolution = self.samp_rate / self.fft_size

        self.window = np.hanning(self.fft_size)

        self.buffer = np.zeros(self.fft_size, dtype=np.complex64)

        self.buf_idx = 0
        self.call_count = 0

        self.last_doppler = 0.0
        self.last_velocity = 0.0
        self.last_dbfs = -120.0

        self.last_print = time.time()

        # --- UDP setup ---
        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def work(self, input_items, output_items):

        samples = input_items[0]

        rms = np.sqrt(np.mean(np.abs(samples)**2))
        dbfs = 20 * np.log10(rms + 1e-12)
        self.last_dbfs = dbfs

        for sample in samples:
            self.buffer[self.buf_idx] = sample
            self.buf_idx += 1

            if self.buf_idx >= self.fft_size:
                self.process_block(self.buffer)
                self.buf_idx = 0

        # Send one UDP packet per work() call
        packet = struct.pack("<fff",
                              self.last_doppler,
                              self.last_velocity,
                              self.last_dbfs)
        try:
            self.sock.sendto(packet, (self.udp_ip, self.udp_port))
        except OSError as e:
            print(f"UDP send failed: {e}")

        if time.time() - self.last_print >= 1:
            print(
                f"Signal Level = {self.last_dbfs:.2f} dBFS | "
                f"Doppler = {self.last_doppler:.2f} Hz | "
                f"Velocity = {self.last_velocity:.3f} m/s"
            )
            self.last_print = time.time()

        return len(samples)

    def process_block(self, block):
        spectrum = np.fft.fftshift(np.fft.fft(block * self.window))
        magnitude = np.abs(spectrum)
        mag_db = 20 * np.log10(magnitude + 1e-12)
        center = self.fft_size // 2

        max_doppler_hz = 2 * self.max_velocity / self.wavelength
        max_doppler_bins = int(np.ceil(max_doppler_hz / self.bin_resolution))
        tone_bin = center + int(round(self.tone_offset / self.bin_resolution))
        lo = max(0, tone_bin - max_doppler_bins)
        hi = min(self.fft_size, tone_bin + max_doppler_bins + 1)

        search_region = mag_db[lo:hi]
        noise_floor = np.median(mag_db)
        local_peak = np.argmax(search_region)
        peak_bin = lo + local_peak
        peak_db = mag_db[peak_bin]

        if (peak_db - noise_floor) < self.threshold:
            return

        peak = float(peak_bin)
        if 1 <= peak_bin < self.fft_size - 1:
            a = mag_db[peak_bin - 1]
            b = mag_db[peak_bin]
            c = mag_db[peak_bin + 1]
            denom = a - 2 * b + c
            if abs(denom) > 1e-12:
                peak += 0.5 * (a - c) / denom

        raw_freq = (peak - center) * self.bin_resolution
        doppler_freq = raw_freq - self.tone_offset
        velocity = doppler_freq * self.wavelength / 2.0

        self.last_doppler = doppler_freq
        self.last_velocity = velocity
        self.call_count += 1
