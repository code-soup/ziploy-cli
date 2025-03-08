# Ziploy CLI

Ziploy CLI is a :zap: lightning fast command‑line script that automates deployment via the [ziploy‑github‑action](https://github.com/code-soup/ziploy-github-action) and can also be run locally. This tool packages your project while excluding files specified in a `.ziployignore` file and then deploys it to a target WordPress website.

**Important:** To successfully receive and apply your deployment, the target WordPress site must have the [Ziploy WordPress Plugin](https://www.ziploy.com) installed. This plugin is required whether you run deployments from GitHub Actions or directly from your local machine.

## Installation

-   Download script
-   add `.ziployconfig` per instructions below
-   run `chmod u+x ./ziploy-cli`
-   run `./ziploy-cli`

## Configuration

Ziploy CLI is configured via a file named `.ziployconfig`. This file (or the `--config` flag) allows you to supply all necessary parameters without needing to type them as command‑line arguments.

### Example `.ziployconfig` File

Below is a sample configuration file with all possible options and a brief description for each:

```dot
# .ziployconfig

# Unique identifier for the deployment
id = my-deploy-id

# Remote host URL – must begin with http:// or https://
origin = https://myexample.com

# Deployment method: "SSH" or "HTTP"
method = SSH

# SSH configuration options (required if method is SSH)
ssh_host = myssh.example.com          # SSH host for remote operations
ssh_user = deployer                   # SSH username
ssh_port = 22                         # SSH port (default: 22)
ssh_key = /home/.ssh/id_rsa    # Optional Path to SSH private key (required if deploying from local machine)
ssh_known_hosts = /home/.ssh/known_hosts  # Optional path to known_hosts file (required if deploying from local machine)


#############################################
# Optional settings:
# Maximum chunk size in bytes (default: 5 MB)
chunk_size = 5242880
```

Place the `.ziployconfig` file in your project root or pass its path explicitly with the `--config` flag when running the tool.

## Ignoring Files

To exclude files and directories from the generated package, create a `.ziployignore` file. This file works similarly to a `.gitignore` file:

-   Use glob patterns to specify what should be ignored.
-   Lines beginning with a `#` are treated as comments.
-   Patterns are defined relative to the project root.

### Example `.ziployignore` File

```dot
# .ziployignore

# Ignore swap files
*.swp

# Ignore Git files and directories
.git*
.gitignore

# Optionally ignore the configuration file
.ziployconfig

# Ignore node_modules directory (often large and managed separately)
node_modules/

# Ignore Python virtual environments
venv/

# Ignore the temporary deployment output folder and ZIP file
__to_ziploy/
_ziploy.zip
```

## Usage

Once your configuration and ignore files are set up, you can deploy your application by running:

```bash
./ziploy-cli
```

This command will:

-   Read settings from the `.ziployconfig` file.
-   Package your project while excluding files that match patterns in `.ziployignore`.
-   Upload and deploy the application via the selected method to origin where Ziploy plugin is installed
-   Provide progress updates and log output to both the console and a log file (ziploy.log).

## Contributing

Please open an issue for bug fixes, improvements, or new features.

## License

This project is licensed under the MIT License.
