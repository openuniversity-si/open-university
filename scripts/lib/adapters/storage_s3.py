"""S3 adapter of the storage port: one object per key in a bucket (the location). boto3 where it is importable (the Fargate
runner), else the aws CLI (the CodeBuild deployer's image has the CLI only). The engine's shared store (DEP8 artifacts)."""
import subprocess

from adapters.storage import check_key

MISSING = ('404', 'NoSuchKey', 'NotFound', '403')  # no s3:ListBucket: a missing key answers 403


class S3Storage:
    name = 's3'

    def __init__(self, bucket, s3=None, run=subprocess.run):
        self.bucket, self.s3, self.run = bucket, s3, run

    def client(self):
        if self.s3 is None:
            try:
                import boto3
                self.s3 = boto3.client('s3')
            except ImportError:
                self.s3 = False
        return self.s3

    def _code(self, error):
        return getattr(error, 'response', {}).get('Error', {}).get('Code')

    def exists(self, key):
        check_key(key)
        client = self.client()
        if client:
            try:
                client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception as error:  # noqa: BLE001 - a 404 is "no"; anything else surfaces on the put
                if self._code(error) in MISSING:
                    return False
                raise
        return self.run(['aws', 's3api', 'head-object', '--bucket', self.bucket, '--key', key],
                        capture_output=True).returncode == 0

    def get(self, key):
        check_key(key)
        client = self.client()
        if client:
            try:
                return client.get_object(Bucket=self.bucket, Key=key)['Body'].read()
            except Exception as error:  # noqa: BLE001
                if self._code(error) in MISSING:
                    return None
                raise
        done = self.run(['aws', 's3', 'cp', f's3://{self.bucket}/{key}', '-', '--only-show-errors'], capture_output=True)
        return done.stdout if done.returncode == 0 else None

    def put(self, key, data):
        check_key(key)
        client = self.client()
        if client:
            client.put_object(Bucket=self.bucket, Key=key, Body=data)
            return
        self.run(['aws', 's3', 'cp', '-', f's3://{self.bucket}/{key}', '--only-show-errors'], input=data, check=True)
