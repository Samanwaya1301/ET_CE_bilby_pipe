import os
import unittest
import bilby_pipe
import shutil
import logging
import sys

from bilby_pipe.utils import BilbyPipeError


class TestParseArgs(unittest.TestCase):
    def test_no_command_line_arguments(self):
        input_args = []
        parser = bilby_pipe.bilbyargparser.BilbyArgParser(
            usage=__doc__, ignore_unknown_config_file_keys=True, allow_abbrev=False
        )
        with self.assertRaises(BilbyPipeError):
            bilby_pipe.main.parse_args(input_args, parser)


class TestUtils(unittest.TestCase):
    def setUp(self):
        self.outdir = "outdir"
        if not os.path.exists(self.outdir):
            os.makedirs(self.outdir)

    def tearDown(self):
        logger = logging.getLogger("bilby_pipe")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        shutil.rmtree(self.outdir, ignore_errors=True)

    def test_directory_creation(self):
        directory = self.outdir + "/test-dir"
        self.assertFalse(os.path.isdir(directory))
        bilby_pipe.utils.check_directory_exists_and_if_not_mkdir(directory)
        self.assertTrue(os.path.isdir(directory))

    def test_set_log_level(self):
        bilby_pipe.utils.setup_logger(log_level="info")
        logger = logging.getLogger("bilby_pipe")
        self.assertEqual(logger.level, logging.INFO)

    def test_set_verbose(self):
        sys.argv.append("-v")
        bilby_pipe.utils.setup_logger(log_level="info")
        logger = logging.getLogger("bilby_pipe")
        self.assertEqual(logger.level, logging.DEBUG)
        sys.argv.pop(-1)

    def test_unknown_log_level(self):
        with self.assertRaises(ValueError):
            bilby_pipe.utils.setup_logger(log_level="NOTANERROR")

    def test_write_to_file(self):
        bilby_pipe.utils.setup_logger(outdir=self.outdir, label="TEST")
        self.assertTrue(os.path.isfile("{}/{}.log".format(self.outdir, "TEST")))

    def test_dict_converter(self):
        key = "test"
        cstd = bilby_pipe.utils.convert_string_to_dict
        self.assertEqual(
            cstd("{'a': 10, 'b': 'string', 'c': 1.0}", key),
            dict(a=10, b="string", c=1.0),
        )
        self.assertEqual(
            cstd("{a: 10, b: 'string', c: 1.0}", key), dict(a=10, b="string", c=1.0)
        )
        self.assertEqual(
            cstd("{a: 10, b: string, c: 1.0}", key), dict(a=10, b="string", c=1.0)
        )
        self.assertEqual(
            cstd("{a= 10, b= 'string, c: 1.0}", key), dict(a=10, b="string", c=1.0)
        )
        self.assertEqual(
            cstd("{a= 10, b : 'string', c: '1.0'}", key), dict(a=10, b="string", c=1.0)
        )
        self.assertEqual(
            cstd('{a= 10, b : "string", c: "1.0"}', key), dict(a=10, b="string", c=1.0)
        )


if __name__ == "__main__":
    unittest.main()
