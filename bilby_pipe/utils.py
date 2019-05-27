"""
A set of generic utilities used in bilby_pipe
"""
import re
import os
import sys
import logging
import math
import ast
import urllib
import urllib.request
import subprocess


class BilbyPipeError(Exception):
    def __init__(self, message):
        super().__init__(message)


duration_lookups = {
    "high_mass": 4,
    "4s": 4,
    "8s": 8,
    "16s": 16,
    "32s": 32,
    "64s": 64,
    "128s": 128,
}


maximum_frequency_lookups = {
    "high_mass": 1024,
    "4s": 1024,
    "8s": 2048,
    "16s": 2048,
    "32s": 2048,
    "64s": 2048,
    "128s": 4096,
}


def get_command_line_arguments():
    """ Helper function to return the list of command line arguments """
    return sys.argv[1:]


def run_command_line(arguments):
    print("\nRunning command $ {}\n".format(" ".join(arguments)))
    subprocess.call(arguments)


def parse_args(input_args, parser, allow_unknown=True):
    """ Parse an argument list using parser generated by create_parser()

    Parameters
    ----------
    input_args: list
        A list of arguments

    Returns
    -------
    args: argparse.Namespace
        A simple object storing the input arguments
    unknown_args: list
        A list of any arguments in `input_args` unknown by the parser

    """

    if len(input_args) == 0:
        raise BilbyPipeError("No command line arguments provided")

    args, unknown_args = parser.parse_known_args(input_args)
    return args, unknown_args


def check_directory_exists_and_if_not_mkdir(directory):
    """ Checks if the given directory exists and creates it if it does not exist

    Parameters
    ----------
    directory: str
        Name of the directory

    """
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.debug("Making directory {}".format(directory))
    else:
        logger.debug("Directory {} exists".format(directory))


def setup_logger(outdir=None, label=None, log_level="INFO", print_version=False):
    """ Setup logging output: call at the start of the script to use

    Parameters
    ----------
    outdir, label: str
        If supplied, write the logging output to outdir/label.log
    log_level: str, optional
        ['debug', 'info', 'warning']
        Either a string from the list above, or an integer as specified
        in https://docs.python.org/2/library/logging.html#logging-levels
    print_version: bool
        If true, print version information
    """

    if "-v" in sys.argv:
        log_level = "DEBUG"

    if isinstance(log_level, str):
        try:
            level = getattr(logging, log_level.upper())
        except AttributeError:
            raise ValueError("log_level {} not understood".format(log_level))
    else:
        level = int(log_level)

    logger = logging.getLogger("bilby_pipe")
    logger.propagate = False
    logger.setLevel(level)

    streams = [isinstance(h, logging.StreamHandler) for h in logger.handlers]
    if len(streams) == 0 or not all(streams):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(name)s %(levelname)-8s: %(message)s", datefmt="%H:%M"
            )
        )
        stream_handler.setLevel(level)
        logger.addHandler(stream_handler)

    if any([isinstance(h, logging.FileHandler) for h in logger.handlers]) is False:
        if label:
            if outdir:
                check_directory_exists_and_if_not_mkdir(outdir)
            else:
                outdir = "."
            log_file = "{}/{}.log".format(outdir, label)
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-8s: %(message)s", datefmt="%H:%M"
                )
            )

            file_handler.setLevel(level)
            logger.addHandler(file_handler)

    for handler in logger.handlers:
        handler.setLevel(level)

    if print_version:
        version = get_version_information()
        logger.info("Running bilby_pipe version: {}".format(version))


def get_version_information():
    version_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "bilby_pipe/.version"
    )
    try:
        with open(version_file, "r") as f:
            return f.readline().rstrip()
    except EnvironmentError:
        print("No version information file '.version' found")


def convert_string_to_dict(string, key):
    """ Convert a string repr of a string to a python dictionary

    Parameters
    ----------
    string: str
        The strng to convert
    key: str
        A key, used for debugging
    """

    string = strip_quotes(string)
    # Convert equals to colons
    string = string.replace("=", ":")
    # Force double quotes around everything
    string = re.sub('(\w+)\s?:\s?("?[^,"}]+"?)', '"\g<1>":"\g<2>"', string)  # noqa
    # Evaluate as a dictionary of str: str
    try:
        dic = ast.literal_eval(string)
    except ValueError as e:
        raise BilbyPipeError("Error {}. Unable to parse {}: {}".format(e, key, string))

    # Convert values to bool/floats/ints where possible
    for key in dic:
        if dic[key].lower() == "true":
            dic[key] = True
        elif dic[key].lower() == "false":
            dic[key] = False
        else:
            dic[key] = string_to_int_float(dic[key])

    return dic


def write_config_file(config_dict, filename):
    """ Writes ini file

    Parameters
    ----------
    config_dict: dict
        Dictionary of parameters for ini file

    Returns
    -------
    filename: str
        Generated ini filename
    """

    if None in config_dict.values():
        raise ValueError("config-dict is not complete")
    with open(filename, "w+") as file:
        for key, val in config_dict.items():
            print("{}={}".format(key, val), file=file)

    return filename


def test_connection():
    """ A generic test to see if the network is reachable """
    try:
        urllib.request.urlopen("https://google.com", timeout=0.1)
    except urllib.error.URLError:
        raise BilbyPipeError(
            "It appears you are not connected to a network and so won't be "
            "able to interface with GraceDB. You may wish to specify the "
            " local-generation argument either in the configuration file "
            "or by passing the --local-generation command line argument"
        )


def strip_quotes(string):
    try:
        return string.replace('"', "").replace("'", "")
    except AttributeError:
        return string


def string_to_int_float(s):
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def is_a_power_of_2(num):
    num = int(num)
    return num != 0 and ((num & (num - 1)) == 0)


def next_power_of_2(x):
    return 1 if x == 0 else 2 ** math.ceil(math.log2(x))


def request_memory_generation_lookup(duration, roq=False):
    """ Function to determine memory required at the data generation step """
    if roq:
        return int(max([8, next_power_of_2(duration / 128 * 64)]))
    else:
        return 8


setup_logger(print_version=True)
logger = logging.getLogger("bilby_pipe")
