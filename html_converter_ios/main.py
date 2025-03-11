folder_name = input("Enter the folder or file path with HTML: ")
if folder_name.strip().strip("/") == "":
    folder_name = "html"

import os
import sys
import logging
from s3 import S3Client

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """
    Main function to upload HTML files to S3.
    """
    # Check if path exists
    if not os.path.exists(folder_name):
        logger.error(f"Path '{folder_name}' not found.")
        print(f"Error: Path '{folder_name}' not found.")
        return False
    
    # Initialize S3 client
    try:
        s3_client = S3Client()
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {str(e)}")
        print(f"Error: Failed to connect to S3 storage. Please check your credentials and network connection.")
        return False
    
    # Handle both single files and directories
    if os.path.isfile(folder_name):
        if not folder_name.lower().endswith(('.html', '.htm')):
            logger.error(f"File '{folder_name}' is not an HTML file.")
            print(f"Error: File '{folder_name}' is not an HTML file.")
            return False
        files_to_process = [(folder_name, os.path.basename(folder_name))]
        html_files_count = 1
    else:
        # Directory processing logic
        prefix = os.path.basename(os.path.normpath(folder_name))
        logger.info(f"Starting upload of HTML files from '{folder_name}' with prefix '{prefix}'")
        
        # Filter for HTML files only
        def is_html_file(file_path):
            return file_path.lower().endswith(('.html', '.htm'))
        
        # Collect all HTML files with their relative paths
        files_to_process = []
        for root, _, files in os.walk(folder_name):
            for file in files:
                file_path = os.path.join(root, file)
                if is_html_file(file_path):
                    relative_path = os.path.relpath(file_path, folder_name)
                    s3_key = os.path.join(prefix, relative_path).replace("\\", "/")
                    files_to_process.append((file_path, s3_key))
        
        html_files_count = len(files_to_process)
        
        if html_files_count == 0:
            logger.warning(f"No HTML files found in '{folder_name}'")
            print(f"Warning: No HTML files found in '{folder_name}'. Nothing to upload.")
            return False
    
    logger.info(f"Found {html_files_count} HTML files to upload")
    print(f"Found {html_files_count} HTML files to upload.")
    
    # Upload files
    uploaded_files = []
    failed_files = []
    
    for file_path, s3_key in files_to_process:
        print(f"Uploading {file_path} to {s3_key}... ", end="", flush=True)
        success, message = s3_client.upload_file(file_path, s3_key)
        
        if success:
            print("✓")
            uploaded_files.append({
                "file": file_path,
                "url": message
            })
        else:
            print("✗")
            failed_files.append({
                "file": file_path,
                "error": message
            })
    
    logger.info(f"Upload complete. Successfully uploaded {len(uploaded_files)} of {html_files_count} HTML files.")
    print(f"\nUpload complete. Successfully uploaded {len(uploaded_files)} of {html_files_count} HTML files.")
    
    if uploaded_files:
        print("\nSuccessfully uploaded files:")
        for item in uploaded_files:
            print(f"  - {item['file']} -> {item['url']}")
    
    if failed_files:
        print("\nFailed to upload files:")
        for item in failed_files:
            print(f"  - {item['file']}: {item['error']}")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

