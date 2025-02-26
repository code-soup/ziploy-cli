import argparse
import os
import sys
import shutil
import logging
import time
import subprocess
import asyncio
import aiohttp
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session():
    # Still used by non-upload parts if needed.
    session = aiohttp.ClientSession()  # Not used for uploads; we use our own aiohttp.ClientSession in async code.
    return session

def setup_logging(verbose):
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("ziploy.log", mode='w')
        ]
    )

def validate_args(args, parser):
    parsed_url = urlparse(args.ziployRemoteHost)
    if parsed_url.scheme not in ('http', 'https'):
         parser.error("Remote host URL must start with http or https.")
    logging.info("All parameters validated successfully.")

def parse_ssh_config(args, parser):
    if len(args.ssh_config) < 3:
        parser.error("SSH configuration requires at least 3 values: SSH_USER, SSH_HOST, SSH_KEY")
    if len(args.ssh_config) == 3:
        ssh_user, ssh_host, ssh_key = [s.strip() for s in args.ssh_config]
        ssh_port = 22
    else:
        ssh_user, ssh_host, ssh_port_str, ssh_key = [s.strip() for s in args.ssh_config[:4]]
        if not ssh_port_str.isdigit():
            parser.error("SSH_PORT must be an integer.")
        ssh_port = int(ssh_port_str)
    if not ssh_user:
        parser.error("SSH_USER must be a non-empty string.")
    if not ssh_host:
        parser.error("SSH_HOST must be a non-empty string.")
    if not ssh_key:
        parser.error("SSH_KEY must be a non-empty string.")
    return {
        "user": ssh_user,
        "host": ssh_host,
        "port": ssh_port,
        "key": ssh_key
    }

def build_api_endpoint(ziployRemoteHost):
    return f"{ziployRemoteHost.rstrip('/')}/wp-json/ziploy/v1/update"

def build_finalize_endpoint(ziployRemoteHost):
    return f"{ziployRemoteHost.rstrip('/')}/wp-json/ziploy/v1/ziploy"

def load_ignore_patterns():
    ignore_patterns = [
        '*.swp',
        '.ziployignore',
        '*.git*',
        'ziploy*',
        'node_modules/*',
        '__to-ziploy',
        '__to-ziploy/',
        '_ziploy.zip',
        'venv',
        'venv/'
    ]
    
    if os.path.isfile('.ziployignore'):
        with open('.ziployignore', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ignore_patterns.append(line)
    return ignore_patterns

def generate_chunks():
    logging.info("Generating Ziploy package using system zip...")
    output_folder = "__to_ziploy"
    zip_filename = os.path.join(output_folder, "_ziploy.zip")
    chunk_size = 5 * 1024 * 1024  # 5MB
    ignore_patterns = load_ignore_patterns()

    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    os.makedirs(output_folder, exist_ok=True)

    zip_command = ["zip", "-r", zip_filename, "."]
    for pattern in ignore_patterns:
        zip_command.extend(["-x", pattern])
    try:
        subprocess.run(zip_command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error during zipping: {e}")
        sys.exit(1)
    logging.info("Ziploy package created successfully.")

    logging.info("Splitting Ziploy package into chunks...")
    try:
        with open(zip_filename, 'rb') as f:
            for chunk_index, chunk in enumerate(iter(lambda: f.read(chunk_size), b'')):
                chunk_filename = os.path.join(output_folder, f"_ziploy.zip.z{chunk_index:03d}")
                with open(chunk_filename, 'wb') as chunk_file:
                    chunk_file.write(chunk)
                logging.debug(f"Created chunk: {chunk_filename}")
    except Exception as e:
        logging.error(f"Error during file splitting: {e}")
        sys.exit(1)
    # Delete the original zip file after splitting into chunks
    try:
        os.remove(zip_filename)
        logging.info(f"Deleted original zip file: {zip_filename}")
    except Exception as e:
        logging.error(f"Failed to delete zip file {zip_filename}: {e}")
    num_chunks = len(os.listdir(output_folder))
    logging.info(f"Ziploy package split into {num_chunks} chunks.")

def get_chunk_files(output_folder):
    # Only consider files with the expected prefix
    return sorted([f for f in os.listdir(output_folder) if f.startswith("_ziploy.zip.z")])

async def async_upload_chunk(session, api_endpoint, chunk_path, verify_ssl, ziployId, last_chunk=False):
    # Read file content synchronously (chunk files are small)
    with open(chunk_path, 'rb') as f:
        file_data = f.read()
    form = aiohttp.FormData()
    form.add_field('id', ziployId)
    if last_chunk:
        form.add_field('last', 'true')
    form.add_field('ziploy', file_data,
                   filename=os.path.basename(chunk_path),
                   content_type='application/octet-stream')
    async with session.post(api_endpoint, data=form, ssl=verify_ssl) as resp:
        resp.raise_for_status()
        json_response = await resp.json()
        return json_response

async def async_upload_chunks(ziployRemoteHost, ziployId, verify_ssl, output_folder, ziployMethod="HTTP", ssh_params=None):
    """
    Asynchronously uploads chunks and, if the ziployMethod is SSH, calls ssh_unzip before finalizing.
    
    Parameters:
        ziployRemoteHost (str): The remote host URL.
        ziployId (str): The ziploy ID.
        verify_ssl (bool): Whether to verify SSL certificates.
        output_folder (str): Folder containing the chunks.
        ziployMethod (str): Either "HTTP" or "SSH".
        ssh_params (dict or None): If SSH is used, a dict with keys 'command' and 'config' (the latter being SSH_CONFIG).
    """
    api_endpoint = build_api_endpoint(ziployRemoteHost)
    finalize_endpoint = build_finalize_endpoint(ziployRemoteHost)
    chunk_files = get_chunk_files(output_folder)
    tasks = []
    
    async with aiohttp.ClientSession() as session:
        for idx, chunk in enumerate(chunk_files):
            last_chunk = (idx == len(chunk_files) - 1)
            chunk_path = os.path.join(output_folder, chunk)
            tasks.append(async_upload_chunk(session, api_endpoint, chunk_path, verify_ssl, ziployId, last_chunk))
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        package, destination = None, None
        for resp in responses:
            if isinstance(resp, Exception):
                logging.error(f"Error uploading chunk: {resp}")
            elif isinstance(resp, dict):
                logging.info(f"Uploaded 1: {resp.get('message', 'No message')}")
                if 'package' in resp and 'destination' in resp:
                    package, destination = resp['package'], resp['destination']
            else:
                logging.info(f"Uploaded 2: {resp}")
        
        # If the method is SSH, call ssh_unzip before finalizing deployment
        if ziployMethod.upper() == "SSH" and ssh_params is not None:
            logging.info("Method is SSH. Calling ssh_unzip before finalizing deployment.")
            ssh_unzip(ssh_params.get("command"), ssh_params.get("config"))
        
        # Finalize deployment and log final response
        async with aiohttp.ClientSession() as session:
            async with session.post(finalize_endpoint,
                                    json={
                                        'id': ziployId,
                                        'package': package,
                                        'destination': destination,
                                        'method': ziployMethod
                                    },
                                    ssl=verify_ssl) as finalize_resp:
                finalize_resp.raise_for_status()
                final_response = await finalize_resp.json()
                logging.info(f"Deployment process initiated successfully. Final response: {final_response}")

def ssh_unzip(command, SSH_CONFIG):
    ssh_command = [
        "ssh", "-i", SSH_CONFIG["key"], "-p", str(SSH_CONFIG["port"]),
        f"{SSH_CONFIG['user']}@{SSH_CONFIG['host']}", command
    ]
    try:
        result = subprocess.run(ssh_command, capture_output=True, text=True, check=True)
        logging.info(f"SSH command executed successfully: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logging.error(f"SSH command failed: {e.stderr}")
        sys.exit(1)

def cleanup():
    output_folder = "__to_ziploy"
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
        logging.info(f"Cleanup completed: {output_folder} deleted.")

def main():
    parser = argparse.ArgumentParser(description="Ziploy CLI: Automates packaging and deployment.")
    parser.add_argument("ziployMethod", type=str, nargs="?", default="SSH")
    parser.add_argument("ziployId", type=str)
    parser.add_argument("ziployRemoteHost", type=str)
    parser.add_argument("ssh_config", nargs="*", metavar="SSH_CONFIG",
                        help=("SSH credentials: if 3 values are provided, they're interpreted as SSH_USER, SSH_HOST, SSH_KEY "
                              "(with default port 22); if 4 values, then as SSH_USER, SSH_HOST, SSH_PORT, SSH_KEY."))
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    validate_args(args, parser)

    if args.ziployMethod.upper() == "SSH":
        SSH_CONFIG = parse_ssh_config(args, parser)
    else:
        SSH_CONFIG = {}

    start_time = time.time()
    generate_chunks()
    # Run asynchronous uploads
    asyncio.run(async_upload_chunks(args.ziployRemoteHost, args.ziployId, False, "__to_ziploy"))
    # Example usage of ssh_unzip:
    # ssh_unzip("unzip /path/to/remote/file.zip", SSH_CONFIG)
    cleanup()
    logging.info(f"Total execution time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()