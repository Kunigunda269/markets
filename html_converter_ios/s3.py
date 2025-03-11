from constants import S3_URL, S3_BUCKET_NAME, S3_ACCESS_KEY, S3_SECRET_ACCESS_KEY
import boto3
import os
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List, Tuple
import logging
from botocore.client import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class S3Client:
    """Client for interacting with S3 storage."""

    def __init__(self):
        """Initialize S3 client with credentials from constants."""
        # Configure S3 client with specific parameters for Timeweb S3
        s3_config = Config(
            signature_version='s3',  # Use older signature version
            s3={'addressing_style': 'path'},  # Use path-style addressing
            retries={'max_attempts': 3, 'mode': 'standard'}
        )

        self.s3_client = boto3.client(
            's3',
            endpoint_url=S3_URL,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY,
            config=s3_config,
            # No region required for Timeweb S3
        )
        self.bucket_name = S3_BUCKET_NAME

        # Ensure the bucket exists and is accessible
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Successfully connected to bucket {self.bucket_name}")
        except ClientError as e:
            logger.error(f"Error accessing bucket {self.bucket_name}: {str(e)}")

    def upload_file(self, file_path: str, object_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Upload a file to an S3 bucket.

        Args:
            file_path: Path to the file to upload
            object_name: S3 object name. If not specified, file_name from file_path is used

        Returns:
            Tuple of (success: bool, message: str)
        """
        # If S3 object_name was not specified, use file_name from file_path
        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            logger.info(f"Uploading {file_path} to {self.bucket_name}/{object_name}")

            # Determine content type based on file extension
            content_type = None
            if file_path.lower().endswith('.html'):
                content_type = 'text/html'
            elif file_path.lower().endswith('.css'):
                content_type = 'text/css'
            elif file_path.lower().endswith('.js'):
                content_type = 'application/javascript'

            # For small files, use put_object instead of upload_file
            if os.path.getsize(file_path) < 5 * 1024 * 1024:  # Less than 5MB
                with open(file_path, 'rb') as file_data:
                    extra_args = {}
                    if content_type:
                        extra_args['ContentType'] = content_type

                    self.s3_client.put_object(
                        Bucket=self.bucket_name,
                        Key=object_name,
                        Body=file_data,
                        **extra_args
                    )
            else:
                # For larger files, use the transfer utility
                extra_args = {}
                if content_type:
                    extra_args['ContentType'] = content_type

                self.s3_client.upload_file(
                    file_path,
                    self.bucket_name,
                    object_name,
                    ExtraArgs=extra_args
                )

            file_url = f"{S3_URL}/{self.bucket_name}/{object_name}"
            return True, file_url
        except FileNotFoundError:
            message = f"File {file_path} not found"
            logger.error(message)
            return False, message
        except ClientError as e:
            message = f"Error uploading to S3: {str(e)}"
            logger.error(message)
            return False, message
        except Exception as e:
            message = f"Unexpected error uploading file: {str(e)}"
            logger.error(message)
            return False, message

    def upload_directory(self, directory_path: str, prefix: str = "") -> List[Dict[str, Any]]:
        """
        Upload all files in a directory to S3 bucket.

        Args:
            directory_path: Local directory containing files to upload
            prefix: Prefix to add to S3 object keys

        Returns:
            List of dicts with upload results
        """
        results = []

        if not os.path.isdir(directory_path):
            logger.error(f"Directory {directory_path} not found")
            return results

        for root, _, files in os.walk(directory_path):
            for file in files:
                local_path = os.path.join(root, file)

                # Create S3 object key with prefix
                relative_path = os.path.relpath(local_path, directory_path)
                s3_key = os.path.join(prefix, relative_path).replace("\\", "/")

                success, message = self.upload_file(local_path, s3_key)
                results.append({
                    "file": local_path,
                    "s3_key": s3_key,
                    "success": success,
                    "message": message
                })

        return results

    def generate_presigned_url(self, object_name: str, expiration: int = 3600) -> Tuple[bool, str]:
        """
        Generate a presigned URL to share an S3 object.

        Args:
            object_name: S3 object name
            expiration: Time in seconds for the URL to remain valid

        Returns:
            Tuple of (success: bool, url or error message: str)
        """
        try:
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
                ExpiresIn=expiration
            )
            return True, response
        except ClientError as e:
            message = f"Error generating presigned URL: {str(e)}"
            logger.error(message)
            return False, message