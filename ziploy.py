import argparse
import os
import sys
import zipfile
import shutil
import requests
import subprocess
import logging
import concurrent.futures
import time

def setup_logging(verbose):
    """Configures logging settings."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("ziploy.log", mode='w')
    ])

def validate_args(args):
    """Validates the provided CLI arguments."""
    if args.ssh_data[2] <= 0 or args.ssh_data[2] > 65535:
        logging.error("Invalid SSH port. Must be between 1-65535.")
        sys.exit(1)
    
    if not os.path.isfile(args.ssh_data[3]):
        logging.error(f"SSH key file not found at {args.ssh_data[3]}")
        sys.exit(1)
    
    if not args.ziployRemoteHost.startswith("http"):
        logging.warning("Remote host URL does not appear to be valid. Ensure it starts with http or https.")
    
    logging.info("All parameters validated successfully.")

def load_ignore_patterns():
    """Loads ignore patterns from the default list and .ziployignore file if present."""
    ignoreArray = ['*.swp', '.ziployignore', '*.git*', 'ziploy', 'node_modules/*', '__to-ziploy/', '__to-ziploy']
    ignoreList = '.ziployignore'
    
    if os.path.isfile(ignoreList):
        with open(ignoreList, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ignoreArray.append(line)
    
    return ignoreArray

def safe_request(method, url, **kwargs):
    """Makes a safe API request with retry handling."""
    for attempt in range(3):  # Retry up to 3 times
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.warning(f"Attempt {attempt + 1}: Request failed - {e}")
            time.sleep(2)  # Wait before retrying
    logging.error("Max retries reached. Exiting.")
    sys.exit(1)

def cleanup():
    """Deletes the __to_ziploy folder and all its contents."""
    output_folder = "__to_ziploy"
    for attempt in range(3):
        try:
            if os.path.exists(output_folder):
                shutil.rmtree(output_folder)
                logging.info(f"Cleanup completed: {output_folder} deleted.")
                return
        except Exception as e:
            logging.warning(f"Cleanup attempt {attempt + 1} failed: {e}")
            time.sleep(2)  # Wait before retrying
    logging.error("Failed to clean up after multiple attempts.")

def upload_chunk(api_endpoint, chunk_path, verify_ssl):
    """Uploads a single file chunk."""
    with open(chunk_path, 'rb') as f:
        files = {'file': f}
        return safe_request("post", api_endpoint, files=files, verify=verify_ssl)

def upload_chunks(ziployRemoteHost, ziployId, verify_ssl):
    """Uploads zip chunks to the remote API and triggers deployment after completion."""
    output_folder = "__to_ziploy"
    api_endpoint = f"{ziployRemoteHost.rstrip('/')}/wp-json/ziploy/v1/update"
    finalize_endpoint = f"{ziployRemoteHost.rstrip('/')}/wp-json/ziploy/v1/ziploy"
    chunk_files = sorted(os.listdir(output_folder))
    package, destination = None, None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(lambda chunk: upload_chunk(api_endpoint, os.path.join(output_folder, chunk), verify_ssl), chunk_files)
    
    for json_response in results:
        logging.info(f"Uploaded: {json_response.get('message', 'No message')}")
        if 'package' in json_response and 'destination' in json_response:
            package, destination = json_response['package'], json_response['destination']
    
    if package and destination:
        logging.info(f"Final Package: {package}, Destination: {destination}")
        response = safe_request("post", finalize_endpoint, json={'id': ziployId, 'package': package, 'destination': destination}, verify=verify_ssl)
        logging.info("Deployment process initiated successfully.")
    cleanup()

def main():
    parser = argparse.ArgumentParser(description="Ziploy CLI: Automates packaging and deployment.")
    parser.add_argument("ziployMethod", type=str, nargs='?', default="SSH")
    parser.add_argument("ziployId", type=str)
    parser.add_argument("ziployRemoteHost", type=str)
    parser.add_argument("--chunk-size", type=int, default=5, help="Chunk size in MB (default: 5MB)")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")
    parser.add_argument("--no-verify", action="store_false", dest="verify_ssl", help="Disable SSL verification (not recommended)")
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logging")
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    validate_args(args)
    
    if args.dry_run:
        logging.info("Dry run mode enabled. No files will be uploaded.")
        sys.exit(0)
    
    start_time = time.time()
    create_ziploy()
    upload_chunks(args.ziployRemoteHost, args.ziployId, args.verify_ssl)
    logging.info(f"Total execution time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()
