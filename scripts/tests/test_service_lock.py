"""Owner-checked cleanup of a dead runner job, without changing another job's lock."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import config
import service_lock


class Cleanup(unittest.TestCase):
    def test_cleanup_passes_the_exact_runner_job_owner_and_reason_to_the_port(self):
        port = mock.Mock()
        service_lock.release('openuniversity-si/open-university', 'vm/train:7#abc', port=port)
        port.unlock.assert_called_once_with('openuniversity-si/open-university', config.get('train.lock_ref'),
            config.get('train.producer') + '@vm/train:7#abc',
            died='runner cleanup after the job ended or restarted (D-291)')


if __name__ == '__main__':
    unittest.main()
