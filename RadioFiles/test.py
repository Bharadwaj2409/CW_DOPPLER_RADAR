#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: CWRADAR
# Author: shreya
# GNU Radio version: 3.10.1.1

from packaging.version import Version as StrictVersion

if __name__ == '__main__':
    import ctypes
    import sys
    if sys.platform.startswith('linux'):
        try:
            x11 = ctypes.cdll.LoadLibrary('libX11.so')
            x11.XInitThreads()
        except:
            print("Warning: failed to XInitThreads()")

from PyQt5 import Qt
from gnuradio import qtgui
from gnuradio.filter import firdes
import sip
from gnuradio import analog
from gnuradio import audio
from gnuradio import blocks
from gnuradio import filter
from gnuradio import gr
from gnuradio.fft import window
import sys
import signal
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
from gnuradio import iio
from gnuradio.qtgui import Range, RangeWidget
from PyQt5 import QtCore
import test_epy_block_1 as epy_block_1  # embedded python block



from gnuradio import qtgui

class test(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "CWRADAR", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("CWRADAR")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except:
            pass
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("GNU Radio", "test")

        try:
            if StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
                self.restoreGeometry(self.settings.value("geometry").toByteArray())
            else:
                self.restoreGeometry(self.settings.value("geometry"))
        except:
            pass

        ##################################################
        # Variables
        ##################################################
        self.tx_attenuation = tx_attenuation = 10
        self.tone = tone = 500
        self.samp_rate = samp_rate = 2400000
        self.rx_gain = rx_gain = 64
        self.reject_fractional_bandwidth = reject_fractional_bandwidth = 0.010
        self.decimation = decimation = 50
        self.audio_gain = audio_gain = 1

        ##################################################
        # Blocks
        ##################################################
        self._tx_attenuation_range = Range(0, 100, 1, 10, 200)
        self._tx_attenuation_win = RangeWidget(self._tx_attenuation_range, self.set_tx_attenuation, "'tx_attenuation'", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._tx_attenuation_win)
        self._tone_range = Range(-2000, 2000, 1, 500, 200)
        self._tone_win = RangeWidget(self._tone_range, self.set_tone, "'tone'", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._tone_win)
        self._rx_gain_range = Range(0, 100, 1, 64, 200)
        self._rx_gain_win = RangeWidget(self._rx_gain_range, self.set_rx_gain, "'rx_gain'", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._rx_gain_win)
        self._reject_fractional_bandwidth_range = Range(0, 0.200, 0.001, 0.010, 200)
        self._reject_fractional_bandwidth_win = RangeWidget(self._reject_fractional_bandwidth_range, self.set_reject_fractional_bandwidth, "'reject_fractional_bandwidth'", "slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._reject_fractional_bandwidth_win)
        self._audio_gain_range = Range(0, 10, 0.1, 1, 200)
        self._audio_gain_win = RangeWidget(self._audio_gain_range, self.set_audio_gain, "'audio_gain'", "counter_slider", float, QtCore.Qt.Horizontal)
        self.top_layout.addWidget(self._audio_gain_win)
        self.qtgui_waterfall_sink_x_1 = qtgui.waterfall_sink_c(
            8192, #size
            window.WIN_RECTANGULAR, #wintype
            0, #fc
            1e6, #bw
            '', #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_waterfall_sink_x_1.set_update_time(0.01)
        self.qtgui_waterfall_sink_x_1.enable_grid(False)
        self.qtgui_waterfall_sink_x_1.enable_axis_labels(True)



        labels = ['', '', '', '', '',
                  '', '', '', '', '']
        colors = [0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
                  1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_waterfall_sink_x_1.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_waterfall_sink_x_1.set_line_label(i, labels[i])
            self.qtgui_waterfall_sink_x_1.set_color_map(i, colors[i])
            self.qtgui_waterfall_sink_x_1.set_line_alpha(i, alphas[i])

        self.qtgui_waterfall_sink_x_1.set_intensity_range(-140, 10)

        self._qtgui_waterfall_sink_x_1_win = sip.wrapinstance(self.qtgui_waterfall_sink_x_1.qwidget(), Qt.QWidget)

        self.top_layout.addWidget(self._qtgui_waterfall_sink_x_1_win)
        self.low_pass_filter_0 = filter.fir_filter_ccf(
            decimation,
            firdes.low_pass(
                1,
                samp_rate,
                tone*2,
                tone/2,
                window.WIN_HAMMING,
                6.76))
        self.iio_pluto_source_0 = iio.fmcomms2_source_fc32('192.168.3.1' if '192.168.3.1' else iio.get_pluto_uri(), [True, True], 32768)
        self.iio_pluto_source_0.set_len_tag_key('packet_len')
        self.iio_pluto_source_0.set_frequency(5500000000)
        self.iio_pluto_source_0.set_samplerate(samp_rate)
        self.iio_pluto_source_0.set_gain_mode(0, 'manual')
        self.iio_pluto_source_0.set_gain(0, rx_gain)
        self.iio_pluto_source_0.set_quadrature(True)
        self.iio_pluto_source_0.set_rfdc(True)
        self.iio_pluto_source_0.set_bbdc(True)
        self.iio_pluto_source_0.set_filter_params('Auto', '', 0, 0)
        self.iio_pluto_sink_0 = iio.fmcomms2_sink_fc32('192.168.3.1' if '192.168.3.1' else iio.get_pluto_uri(), [True, True], 32768, False)
        self.iio_pluto_sink_0.set_len_tag_key('')
        self.iio_pluto_sink_0.set_bandwidth(20000000)
        self.iio_pluto_sink_0.set_frequency(5500000000)
        self.iio_pluto_sink_0.set_samplerate(samp_rate)
        self.iio_pluto_sink_0.set_attenuation(0, tx_attenuation)
        self.iio_pluto_sink_0.set_filter_params('Auto', '', 0, 0)
        self.epy_block_1 = epy_block_1.doppler_velocity(samp_rate=48000, fft_size=8192, center_freq_hz=5500000000, print_every_n=5, noise_thresh_db=16, tone_offset_hz=500, max_velocity_mps=5, udp_ip='127.0.0.1', udp_port=5005, max_targets=5)
        self.blocks_multiply_const_vxx_0 = blocks.multiply_const_cc(audio_gain)
        self.blocks_complex_to_real_0 = blocks.complex_to_real(1)
        self.band_reject_filter_0 = filter.fir_filter_ccf(
            1,
            firdes.band_reject(
                1,
                samp_rate/decimation,
                tone*(1-reject_fractional_bandwidth),
                tone*(1+reject_fractional_bandwidth),
                tone*reject_fractional_bandwidth,
                window.WIN_HAMMING,
                6.76))
        self.audio_sink_0 = audio.sink(48000, '', True)
        self.analog_sig_source_x_0 = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE, tone, 1, 0, 0)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.analog_sig_source_x_0, 0), (self.iio_pluto_sink_0, 0))
        self.connect((self.band_reject_filter_0, 0), (self.blocks_multiply_const_vxx_0, 0))
        self.connect((self.band_reject_filter_0, 0), (self.epy_block_1, 0))
        self.connect((self.band_reject_filter_0, 0), (self.qtgui_waterfall_sink_x_1, 0))
        self.connect((self.blocks_complex_to_real_0, 0), (self.audio_sink_0, 0))
        self.connect((self.blocks_multiply_const_vxx_0, 0), (self.blocks_complex_to_real_0, 0))
        self.connect((self.iio_pluto_source_0, 0), (self.low_pass_filter_0, 0))
        self.connect((self.low_pass_filter_0, 0), (self.band_reject_filter_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("GNU Radio", "test")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_tx_attenuation(self):
        return self.tx_attenuation

    def set_tx_attenuation(self, tx_attenuation):
        self.tx_attenuation = tx_attenuation
        self.iio_pluto_sink_0.set_attenuation(self.tx_attenuation)

    def get_tone(self):
        return self.tone

    def set_tone(self, tone):
        self.tone = tone
        self.analog_sig_source_x_0.set_frequency(self.tone)
        self.band_reject_filter_0.set_taps(firdes.band_reject(1, self.samp_rate/self.decimation, self.tone*(1-self.reject_fractional_bandwidth), self.tone*(1+self.reject_fractional_bandwidth), self.tone*self.reject_fractional_bandwidth, window.WIN_HAMMING, 6.76))
        self.low_pass_filter_0.set_taps(firdes.low_pass(1, self.samp_rate, self.tone*2, self.tone/2, window.WIN_HAMMING, 6.76))

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.analog_sig_source_x_0.set_sampling_freq(self.samp_rate)
        self.band_reject_filter_0.set_taps(firdes.band_reject(1, self.samp_rate/self.decimation, self.tone*(1-self.reject_fractional_bandwidth), self.tone*(1+self.reject_fractional_bandwidth), self.tone*self.reject_fractional_bandwidth, window.WIN_HAMMING, 6.76))
        self.iio_pluto_sink_0.set_samplerate(self.samp_rate)
        self.iio_pluto_source_0.set_samplerate(self.samp_rate)
        self.low_pass_filter_0.set_taps(firdes.low_pass(1, self.samp_rate, self.tone*2, self.tone/2, window.WIN_HAMMING, 6.76))

    def get_rx_gain(self):
        return self.rx_gain

    def set_rx_gain(self, rx_gain):
        self.rx_gain = rx_gain
        self.iio_pluto_source_0.set_gain(0, self.rx_gain)

    def get_reject_fractional_bandwidth(self):
        return self.reject_fractional_bandwidth

    def set_reject_fractional_bandwidth(self, reject_fractional_bandwidth):
        self.reject_fractional_bandwidth = reject_fractional_bandwidth
        self.band_reject_filter_0.set_taps(firdes.band_reject(1, self.samp_rate/self.decimation, self.tone*(1-self.reject_fractional_bandwidth), self.tone*(1+self.reject_fractional_bandwidth), self.tone*self.reject_fractional_bandwidth, window.WIN_HAMMING, 6.76))

    def get_decimation(self):
        return self.decimation

    def set_decimation(self, decimation):
        self.decimation = decimation
        self.band_reject_filter_0.set_taps(firdes.band_reject(1, self.samp_rate/self.decimation, self.tone*(1-self.reject_fractional_bandwidth), self.tone*(1+self.reject_fractional_bandwidth), self.tone*self.reject_fractional_bandwidth, window.WIN_HAMMING, 6.76))

    def get_audio_gain(self):
        return self.audio_gain

    def set_audio_gain(self, audio_gain):
        self.audio_gain = audio_gain
        self.blocks_multiply_const_vxx_0.set_k(self.audio_gain)




def main(top_block_cls=test, options=None):

    if StrictVersion("4.5.0") <= StrictVersion(Qt.qVersion()) < StrictVersion("5.0.0"):
        style = gr.prefs().get_string('qtgui', 'style', 'raster')
        Qt.QApplication.setGraphicsSystem(style)
    qapp = Qt.QApplication(sys.argv)

    tb = top_block_cls()

    tb.start()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()

if __name__ == '__main__':
    main()
