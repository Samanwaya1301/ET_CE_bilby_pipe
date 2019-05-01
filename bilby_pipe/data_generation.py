#!/usr/bin/env python
"""
Module containing the tools for data generation
"""
from __future__ import division, print_function

import os
import sys

import matplotlib
import numpy as np
import gwpy

matplotlib.use("agg")  # noqa
import bilby
from bilby.gw.detector import PowerSpectralDensity

from bilby_pipe.utils import (
    logger,
    BilbyPipeError,
    convert_string_to_dict,
    is_a_power_of_2,
    test_connection,
)
from bilby_pipe.main import DataDump, parse_args
from bilby_pipe.input import Input
from bilby_pipe.parser import create_parser

try:
    import nds2  # noqa
except ImportError:
    logger.warning(
        "You do not have nds2 (python-nds2-client) installed. You may "
        " experience problems accessing interferometer data."
    )

try:
    import LDAStools  # noqa
except ImportError:
    logger.warning(
        "You do not have LDAStools (python-ldas-tools-framecpp) installed."
        " You may experience problems accessing interferometer data."
    )


class DataGenerationInput(Input):
    """ Handles user-input and creation of intermediate interferometer list

    Parameters
    ----------
    parser: configargparse.ArgParser, optional
        The parser containing the command line / ini file inputs
    args_list: list, optional
        A list of the arguments to parse. Defauts to `sys.argv[1:]`
    create_data: bool
        If false, no data is generated (used for testing)

    """

    def __init__(self, args, unknown_args, create_data=True):

        np.random.seed(args.generation_seed)

        logger.info("Command line arguments: {}".format(args))
        logger.info("Unknown command line arguments: {}".format(unknown_args))
        self.meta_data = dict(
            command_line_args=args,
            unknown_command_line_args=unknown_args,
            injection_parameters=None,
        )
        self.ini = args.ini
        self.create_plots = args.create_plots
        self.cluster = args.cluster
        self.process = args.process
        self.idx = args.idx
        self.x509userproxy = args.X509
        self.prior_file = args.prior_file
        self.deltaT = args.deltaT
        self.default_prior = args.default_prior
        self.detectors = args.detectors
        self.channel_dict = args.channel_dict
        self.data_dict = args.data_dict
        self.data_format = args.data_format
        self.duration = args.duration
        self.post_trigger_duration = args.post_trigger_duration
        self.deltaT = args.deltaT
        self.sampling_frequency = args.sampling_frequency
        self.psd_length = args.psd_length
        self.psd_fractional_overlap = args.psd_fractional_overlap
        self.psd_start_time = args.psd_start_time
        self.psd_method = args.psd_method
        self.psd_dict = args.psd_dict
        self.zero_noise = args.zero_noise
        self.minimum_frequency = args.minimum_frequency
        self.maximum_frequency = args.maximum_frequency
        self.outdir = args.outdir
        self.label = args.label
        self.roq_folder = args.roq_folder
        self.frequency_domain_source_model = args.frequency_domain_source_model
        self.waveform_approximant = args.waveform_approximant
        self.reference_frequency = args.reference_frequency
        self.calibration_model = args.calibration_model
        self.spline_calibration_nodes = args.spline_calibration_nodes
        self.spline_calibration_envelope_dict = args.spline_calibration_envelope_dict
        if create_data:
            self.create_data(args)

    def create_data(self, args):
        """ Function to iterarate through data generation method

        Note, the data methods are mutually exclusive and only one can given to
        the parser.

        Parameters
        ----------
        args: Namespace
            Input arguments

        Raises
        ------
        BilbyPipeError:
            If no data is generated

        """

        self.data_set = False
        self.injection_file = args.injection_file
        self.gaussian_noise = args.gaussian_noise

        # The following are all mutually exclusive methods to set the data
        if self.gaussian_noise:
            if args.injection_file is not None:
                self._set_interferometers_from_injection()
            else:
                raise BilbyPipeError("Unable to set data: no injection file")
        elif self.data_set is False and args.gracedb is not None:
            self.gracedb = args.gracedb
            self._set_interferometers_from_data()
        elif self.data_set is False and args.gps_file is not None:
            self.gps_file = args.gps_file
            self._set_interferometers_from_data()
        elif self.data_set is False and args.trigger_time is not None:
            self.trigger_time = args.trigger_time
            self._set_interferometers_from_data()

        if self.data_set is False:
            raise BilbyPipeError("Unable to set data")

    @property
    def cluster(self):
        return self._cluster

    @cluster.setter
    def cluster(self, cluster):
        try:
            self._cluster = int(cluster)
        except (ValueError, TypeError):
            logger.debug("Unable to convert input `cluster` to type int")
            self._cluster = cluster

    @property
    def process(self):
        return self._process

    @process.setter
    def process(self, process):
        try:
            self._process = int(process)
        except (ValueError, TypeError):
            logger.debug("Unable to convert input `process` to type int")
            self._process = process

    @property
    def psd_length(self):
        """ Integer number of durations to use for generating the PSD """
        return self._psd_length

    @psd_length.setter
    def psd_length(self, psd_length):
        if isinstance(psd_length, int):
            self._psd_length = psd_length
            self.psd_duration = psd_length * self.duration

            logger.info(
                "PSD duration set to {}s, {}x the duration {}s".format(
                    self.psd_duration, psd_length, self.duration
                )
            )
        else:
            raise BilbyPipeError("Unable to set the psd length")

    @property
    def psd_start_time(self):
        """ The PSD start time relative to segment start time """
        if self._psd_start_time is not None:
            return self._psd_start_time
        elif self.trigger_time is not None:
            psd_start_time = -self.psd_duration
            logger.info("Using default PSD start time {}".format(psd_start_time))
            return psd_start_time
        else:
            raise BilbyPipeError("PSD start time not set")

    @psd_start_time.setter
    def psd_start_time(self, psd_start_time):
        if psd_start_time is None:
            self._psd_start_time = None
        else:
            self._psd_start_time = psd_start_time
            logger.info(
                "PSD start-time set to {} relative to segment start time".format(
                    self._psd_start_time
                )
            )

    @property
    def parameter_conversion(self):
        if "binary_neutron_star" in self.frequency_domain_source_model:
            return bilby.gw.conversion.convert_to_lal_binary_neutron_star_parameters
        elif "binary_black_hole" in self.frequency_domain_source_model:
            return bilby.gw.conversion.convert_to_lal_binary_black_hole_parameters
        else:
            return None

    @property
    def data_dict(self):
        return self._data_dict

    @data_dict.setter
    def data_dict(self, data_dict):
        if data_dict is not None:
            self._data_dict = convert_string_to_dict(data_dict, "data-dict")
        else:
            logger.debug("data-dict set to None")
            self._data_dict = None

    @property
    def channel_dict(self):
        return self._channel_dict

    @channel_dict.setter
    def channel_dict(self, channel_dict):
        if channel_dict is not None:
            self._channel_dict = convert_string_to_dict(channel_dict, "channel-dict")
        else:
            logger.debug("channel-dict set to None")
            self._channel_dict = None

    def get_channel_type(self, det):
        """ Help method to read the channel_dict and print useful messages """
        if self.channel_dict is None:
            raise BilbyPipeError("No channel-dict argument provided")
        if det in self.channel_dict:
            return self.channel_dict[det]
        else:
            raise BilbyPipeError(
                "Detector {} not given in the channel-dict".format(det)
            )

    @property
    def detectors(self):
        """ A list of the detectors to search over, e.g., ['H1', 'L1'] """
        return self._detectors

    @detectors.setter
    def detectors(self, detectors):
        """ Handles various types of user input """
        if isinstance(detectors, list):
            if len(detectors) == 1:
                det_list = self._convert_string_to_list(detectors[0])
            else:
                det_list = detectors
        else:
            raise ValueError("Input `detectors` = {} not understood".format(detectors))

        det_list.sort()
        det_list = [det.upper() for det in det_list]
        self._detectors = det_list

    @property
    def sampling_frequency(self):
        return self._sampling_frequency

    @sampling_frequency.setter
    def sampling_frequency(self, sampling_frequency):
        if is_a_power_of_2(sampling_frequency):
            logger.warning(
                "Sampling frequency not a power of 2, this can cause problems"
            )
        self._sampling_frequency = sampling_frequency

    @property
    def trigger_time(self):
        return self._trigger_time

    @trigger_time.setter
    def trigger_time(self, trigger_time):
        self._trigger_time = trigger_time

    @property
    def gracedb(self):
        """ The gracedb of the candidate """
        return self._gracedb

    @gracedb.setter
    def gracedb(self, gracedb):
        """ Set the gracedb ID

        At setting, will load the json candidate data and path to the frame
        cache file.

        Parameters
        ----------
        gracedb: str
            The gracedb UID string

        """
        if gracedb is None:
            self._gracedb = None
        else:
            logger.info("Setting gracedb id to {}".format(gracedb))
            test_connection()
            candidate = bilby.gw.utils.gracedb_to_json(
                gracedb, outdir=self.data_directory, cred=self.x509userproxy
            )
            self.meta_data["gracedb_candidate"] = candidate
            self._gracedb = gracedb
            self.trigger_time = candidate["gpstime"]

    def _parse_gps_file(self):
        """ Reads in the GPS file selects the required time and set the trigger time

        Note, the gps_file setter method is defined in bilby_pipe.input
        """
        gps_start_times = self.read_gps_file()
        self.start_time = gps_start_times[self.idx]
        self.trigger_time = self.start_time + self.duration - self.post_trigger_duration

    def _set_interferometers_from_injection(self):
        """ Method to generate the interferometers data from an injection """

        self.injection_parameters = self.injection_df.iloc[self.idx].to_dict()
        self.meta_data["injection_parameters"] = self.injection_parameters
        self.trigger_time = self.injection_parameters["geocent_time"]

        logger.info(
            "injected waveform minimum frequency: " + str(self.minimum_frequency)
        )
        logger.info(
            "injected waveform maximum frequency: " + str(self.maximum_frequency)
        )

        waveform_arguments = dict(
            waveform_approximant=self.waveform_approximant,
            reference_frequency=self.reference_frequency,
            minimum_frequency=self.minimum_frequency,
        )

        waveform_generator = bilby.gw.WaveformGenerator(
            duration=self.duration,
            sampling_frequency=self.sampling_frequency,
            frequency_domain_source_model=self.bilby_frequency_domain_source_model,
            parameter_conversion=self.parameter_conversion,
            waveform_arguments=waveform_arguments,
        )

        ifos = bilby.gw.detector.InterferometerList(self.detectors)

        if self.psd_dict is not None:
            for ifo in ifos:
                if ifo.name in self.psd_dict.keys():
                    self._set_psd_from_file(ifo)

        if self.zero_noise:
            ifos.set_strain_data_from_zero_noise(
                sampling_frequency=self.sampling_frequency,
                duration=self.duration,
                start_time=self.trigger_time - self.duration / 2,
            )
        else:
            ifos.set_strain_data_from_power_spectral_densities(
                sampling_frequency=self.sampling_frequency,
                duration=self.duration,
                start_time=self.trigger_time - self.duration / 2,
            )

        ifos.inject_signal(
            waveform_generator=waveform_generator, parameters=self.injection_parameters
        )

        self.interferometers = ifos

    def inject_signal_into_time_domain_data(self, data, ifo):
        """ Method to inject a signal into time-domain interferometer data

        Parameters
        ----------
        data: gwpy.timeseries.TimeSeries
            The data into which to inject the signal
        ifo: bilby.gw.detector.Interferometer
            The interferometer for which the data relates too

        Returns
        -------
        data_and_signal: gwpy.timeseries.TimeSeries
            The data with the signal added

        """

        if hasattr(self, "injection_parameters"):
            parameters = self.injection_parameters
        else:
            parameters = self.injection_df.iloc[self.idx].to_dict()
            parameters["geocent_time"] = np.random.uniform(
                self.trigger_time - self.deltaT / 2.0,
                self.trigger_time + self.deltaT / 2.0,
            )
            self.meta_data["injection_parameters"] = parameters
            self.injection_parameters = parameters

        waveform_arguments = dict(
            waveform_approximant=self.waveform_approximant,
            reference_frequency=self.reference_frequency,
            minimum_frequency=self.minimum_frequency,
        )

        waveform_generator = bilby.gw.WaveformGenerator(
            duration=self.duration,
            sampling_frequency=self.sampling_frequency,
            frequency_domain_source_model=self.bilby_frequency_domain_source_model,
            parameter_conversion=self.parameter_conversion,
            waveform_arguments=waveform_arguments,
        )

        if self.create_plots:
            outdir = self.data_directory
            label = self.label
        else:
            outdir = None
            label = None

        signal_and_data, meta_data = bilby.gw.detector.inject_signal_into_gwpy_timeseries(
            data=data,
            waveform_generator=waveform_generator,
            parameters=parameters,
            det=ifo.name,
            outdir=outdir,
            label=label,
        )
        ifo.meta_data = meta_data
        return signal_and_data

    @property
    def psd_dict(self):
        return self._psd_dict

    @psd_dict.setter
    def psd_dict(self, psd_dict):
        if psd_dict is not None:
            self._psd_dict = convert_string_to_dict(psd_dict, "psd-dict")
        else:
            logger.debug("psd-dict set to None")
            self._psd_dict = None

    def _set_psd_from_file(self, ifo):
        psd_file = self.psd_dict[ifo.name]
        logger.info("Setting {} PSD from file {}".format(ifo.name, psd_file))
        ifo.power_spectral_density = PowerSpectralDensity.from_power_spectral_density_file(
            psd_file=psd_file
        )

    def _set_interferometers_from_data(self):
        """ Method to generate the interferometers data from data"""
        end_time = self.start_time + self.duration
        ifo_list = []
        for det in self.detectors:
            logger.info("Getting analysis-segment data for {}".format(det))
            data = self._get_data(
                det, self.get_channel_type(det), self.start_time, end_time
            )
            ifo = bilby.gw.detector.get_empty_interferometer(det)
            if self.injection_file is not None:
                data = self.inject_signal_into_time_domain_data(data, ifo)
            ifo.strain_data.set_from_gwpy_timeseries(data)

            if self.psd_dict is not None and det in self.psd_dict:
                self._set_psd_from_file(ifo)
            else:
                logger.info("Setting PSD for {} from data".format(det))
                # psd_start_time is given relative to the segment start time
                # so here we calculate the actual start time
                actual_psd_start_time = self.start_time + self.psd_start_time
                actual_psd_end_time = actual_psd_start_time + self.psd_duration
                logger.info("Getting psd-segment data for {}".format(det))
                psd_data = self._get_data(
                    det,
                    self.get_channel_type(det),
                    actual_psd_start_time,
                    actual_psd_end_time,
                )
                roll_off = 0.2
                psd_alpha = 2 * roll_off / self.duration
                overlap = self.psd_fractional_overlap * self.duration
                logger.info(
                    "PSD settings: window=Tukey, Tukey-alpha={} roll-off={},"
                    " overlap={}, method={}".format(
                        psd_alpha, roll_off, overlap, self.psd_method
                    )
                )
                psd = psd_data.psd(
                    fftlength=self.duration,
                    overlap=overlap,
                    window=("tukey", psd_alpha),
                    method=self.psd_method,
                )
                ifo.power_spectral_density = PowerSpectralDensity(
                    frequency_array=psd.frequencies.value, psd_array=psd.value
                )
            ifo_list.append(ifo)
        self.interferometers = bilby.gw.detector.InterferometerList(ifo_list)

    def _get_data(self, det, channel_type, start_time, end_time):
        """ Read in data using gwpy

        This first uses the `gwpy.timeseries.TimeSeries.get()` method to acces
        the data, if this fails, it then attempts to use `fetch_open_data()` as
        a fallback.

        Parameters
        ----------
        channel_type: str
            The full channel name is formed from <det>:<channel_type>, see
            bilby_pipe_generation --help for more information. If given as a
            list each type will be tried and the first success returned.
        start_time, end_time: float
            GPS start and end time of segment
        """
        data = None

        channel = "{}:{}".format(det, channel_type)

        if data is None and self.data_dict is not None:
            data = self._gwpy_read(det, channel, start_time, end_time)
        if data is None:
            data = self._gwpy_get(det, channel, start_time, end_time)
        if data is None:
            data = self._gwpy_fetch_open_data(det, channel, start_time, end_time)

        data = data.resample(self.sampling_frequency)
        return data

    def _gwpy_read(self, det, channel, start_time, end_time):
        logger.debug("data-dict provided, attempt read of data")

        if self.data_format is not None:
            kwargs = dict(format=self.data_format)
            logger.info(
                "Calling TimeSeries.read('{}', '{}', start={}, end={}, format='{}')".format(
                    self.data_dict[det], channel, start_time, end_time, self.data_format
                )
            )
        else:
            kwargs = {}
            logger.info(
                "Calling TimeSeries.read('{}', '{}', start={}, end={})".format(
                    self.data_dict[det], channel, start_time, end_time
                )
            )

        try:
            data = gwpy.timeseries.TimeSeries.read(
                self.data_dict[det], channel, start=start_time, end=end_time, **kwargs
            )
            if data.duration.value != self.duration:
                logger.warning(
                    "Unable to read in requested {}s duration of data from {}"
                    " only {}s available".format(
                        self.duration, self.data_dict[det], data.duration.value
                    )
                )
                data = None
            return data
        except ValueError as e:
            logger.info("Reading of data failed with error {}".format(e))
            return None

    def _gwpy_get(self, det, channel, start_time, end_time):
        logger.debug("Attempt to locate data")
        logger.info(
            "Calling TimeSeries.get('{}', start={}, end={})".format(
                channel, start_time, end_time
            )
        )
        try:
            data = gwpy.timeseries.TimeSeries.get(
                channel, start_time, end_time, verbose=False
            )
            return data
        except RuntimeError as e:
            logger.info("Unable to read data for channel {}".format(channel))
            logger.debug("Error message {}".format(e))
        except ImportError:
            logger.info("Unable to read data as NDS2 is not installed")

    def _gwpy_fetch_open_data(self, det, channel, start_time, end_time):
        logger.info(
            "Previous attempts to download data failed, trying with `fetch_open_data`"
        )
        data = gwpy.timeseries.TimeSeries.fetch_open_data(det, start_time, end_time)
        return data

    @property
    def interferometers(self):
        """ A bilby.gw.detector.InterferometerList """
        try:
            return self._interferometers
        except AttributeError:
            raise ValueError(
                "interferometers unset, did you provide a set-data method?"
            )

    def add_calibration_model_to_interferometers(self, ifo):
        if self.calibration_model == "CubicSpline":
            ifo.calibration_model = bilby.gw.calibration.CubicSpline(
                prefix="recalib_{}_".format(ifo.name),
                minimum_frequency=ifo.minimum_frequency,
                maximum_frequency=ifo.maximum_frequency,
                n_points=self.spline_calibration_nodes,
            )
        else:
            raise BilbyPipeError(
                "calibration model {} not implemented".format(self.calibration_model)
            )

    @interferometers.setter
    def interferometers(self, interferometers):
        for ifo in interferometers:
            if isinstance(ifo, bilby.gw.detector.Interferometer) is False:
                raise BilbyPipeError("ifo={} is not a bilby Interferometer".format(ifo))
            if self.minimum_frequency is not None:
                ifo.minimum_frequency = self.minimum_frequency_dict[ifo.name]
            if self.maximum_frequency is not None:
                ifo.maximum_frequency = self.maximum_frequency_dict[ifo.name]
            if self.calibration_model is not None:
                self.add_calibration_model_to_interferometers(ifo)

        self._interferometers = interferometers
        self.data_set = True
        if self.create_plots:
            interferometers.plot_data(outdir=self.data_directory, label=self.label)

    def save_interferometer_list(self):
        """ Method to dump the saved data to disk for later analysis """
        data_dump = DataDump(
            outdir=self.data_directory,
            label=self.label,
            idx=self.idx,
            trigger_time=self.trigger_time,
            interferometers=self.interferometers,
            meta_data=self.meta_data,
        )
        data_dump.to_pickle()

    def save_roq_weights(self):
        logger.info(
            "Using the ROQ likelihood with roq-folder={}".format(self.roq_folder)
        )
        freq_nodes_linear = np.load(self.roq_folder + "/fnodes_linear.npy")
        freq_nodes_quadratic = np.load(self.roq_folder + "/fnodes_quadratic.npy")

        basis_matrix_linear = np.load(self.roq_folder + "/B_linear.npy").T
        basis_matrix_quadratic = np.load(self.roq_folder + "/B_quadratic.npy").T

        waveform_arguments = dict()
        waveform_arguments["frequency_nodes_linear"] = freq_nodes_linear
        waveform_arguments["frequency_nodes_quadratic"] = freq_nodes_quadratic

        waveform_generator = bilby.gw.waveform_generator.WaveformGenerator(
            sampling_frequency=self.interferometers.sampling_frequency,
            duration=self.interferometers.duration,
            frequency_domain_source_model=bilby.gw.source.roq,
            start_time=self.interferometers.start_time,
            waveform_arguments=waveform_arguments,
        )

        likelihood = bilby.gw.likelihood.ROQGravitationalWaveTransient(
            interferometers=self.interferometers,
            priors=self.priors,
            waveform_generator=waveform_generator,
            linear_matrix=basis_matrix_linear,
            quadratic_matrix=basis_matrix_quadratic,
        )

        weight_file = os.path.join(
            self.data_directory, self.label + "_roq_weights.json"
        )

        likelihood.save_weights(weight_file)


def create_generation_parser():
    return create_parser(top_level=False)


def main():
    args, unknown_args = parse_args(sys.argv[1:], create_generation_parser())
    data = DataGenerationInput(args, unknown_args)
    data.save_interferometer_list()
    if args.likelihood_type == "ROQGravitationalWaveTransient":
        data.save_roq_weights()
