"""The s3 adapter of the storage port: boto3 client path and aws CLI path, both faked. No network."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from adapters import storage, storage_s3  # noqa: E402


class Missing(Exception):
    response = {'Error': {'Code': '404'}}


class Client:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise Missing()

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise Missing()
        import io
        return {'Body': io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


class S3(unittest.TestCase):
    def test_boto3_path(self):
        store = storage_s3.S3Storage('b', s3=Client())
        self.assertFalse(store.exists('a/b.zip'))
        self.assertIsNone(store.get('a/b.zip'))
        store.put('a/b.zip', b'x')
        self.assertTrue(store.exists('a/b.zip'))
        self.assertEqual(store.get('a/b.zip'), b'x')

    def test_cli_path(self):
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw))
            return subprocess.CompletedProcess(cmd, 0 if cmd[1] != 's3api' else 1, stdout=b'y')
        store = storage_s3.S3Storage('b', s3=False, run=run)
        self.assertFalse(store.exists('k'))
        store.put('k', b'z')
        self.assertEqual(store.get('k'), b'y')
        self.assertEqual(calls[1][0][0], 'aws')
        self.assertEqual(calls[1][1]['input'], b'z')

    def test_keys_are_checked_and_the_port_selects_it(self):
        with self.assertRaises(storage.StorageError):
            storage_s3.S3Storage('b', s3=Client()).put('../x', b'')
        self.assertEqual(storage.open_store('bucket', 's3').name, 's3')


if __name__ == '__main__':
    unittest.main(verbosity=1)
