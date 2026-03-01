# End-to-End AWS EC2 Deployment Guide

This guide covers exactly how to deploy your `mcp_server.py` to an AWS EC2 instance, ensuring it runs 24/7 in the background and properly pre-caches the 50+ Caribbean Flow URLs upon startup.

## Phase 1: Launch the EC2 Instance

1. Log into your **AWS Console**.
2. Go to **EC2** and click **Launch Instance**.
3. **Name:** `discoverflow-mcp-server`
4. **OS (AMI):** Select **Ubuntu Server 22.04 LTS (HVM), SSD Volume Type**.
5. **Instance Type:** Select **t3.small** (2 vCPUs, 2 GB RAM). 
   *(Note: 2GB RAM is highly recommended for running headless Chromium with 50+ cached pages).*
6. **Key Pair:** Create a new key pair (RSA, `.pem`) and download it. You will need this to SSH in.
7. **Network Settings / Security Group:**
   - Allow **SSH traffic** from **Anywhere (0.0.0.0/0)** (or just your IP for better security).
   - Allow **Custom TCP** on port **8080** from **Anywhere (0.0.0.0/0)**. *This is crucial, as port 8080 is what the MCP SSE server binds to.*
8. **Configure Storage:** Change the root volume to **10 GB gp3** (or gp2).
9. Click **Launch Instance**.

## Phase 2: Copy Your Code to the Server

Wait for the instance state to show "Running". Find its **Public IPv4 address**.

You can upload your files via SFTP (like FileZilla), use Git, or simply use `scp` from your local Windows terminal.

From your local machine (where your `.pem` key is downloaded), run:
```powershell
# Assuming your key is in your Downloads folder
# Replace <YOUR-EC2-IP> with the actual Public IPv4 address
scp -i $HOME\Downloads\your-key.pem -r "C:\Users\girid\OneDrive\GEN AI\swp" "ubuntu@<YOUR-EC2-IP>:/home/ubuntu/discoverflow-mcp"
```

## Phase 3: Install Dependencies on EC2

Open a terminal to SSH into your EC2 instance:
```powershell
ssh -i $HOME\Downloads\your-key.pem ubuntu@<YOUR-EC2-IP>
```

Once inside the Ubuntu server, run these commands exactly in order:

```bash
# 1. Update system packages
sudo apt update && sudo apt upgrade -y

# 2. Install Python and virtual environment tools
sudo apt install python3-pip python3-venv -y

# 3. Enter the project directory
cd /home/ubuntu/discoverflow-mcp

# 4. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 5. Install Python dependencies
pip install -r requirements.txt

# 6. Install Playwright and its system browser dependencies
playwright install chromium
sudo playwright install-deps
```

## Phase 4: Run the Server 24/7 (Daemonizing)

You don't want the server to stop when you close your SSH terminal. We will use `systemd` to keep it running forever in the background and auto-restart if it crashes.

1. Open a new service definition file:
```bash
sudo nano /etc/systemd/system/mcp-server.service
```

2. Paste the following configuration exactly as-is:
```ini
[Unit]
Description=DiscOverflow MCP Scraper Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/discoverflow-mcp
ExecStart=/home/ubuntu/discoverflow-mcp/venv/bin/python /home/ubuntu/discoverflow-mcp/mcp_server.py
Restart=always
RestartSec=5

# Playwright needs this so it doesn't crash in background services
Environment="PLAYWRIGHT_BROWSERS_PATH=0"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```
*(Save and exit nano by pressing `Ctrl+O`, `Enter`, `Ctrl+X`)*

3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-server
sudo systemctl start mcp-server
```

4. **Verify it is successfully pre-warming!**
Watch the live logs to ensure Playwright is gracefully scraping the 50+ URLs:
```bash
sudo journalctl -u mcp-server -f
```
*(Press `Ctrl+C` to exit the logging screen once you see "Cache warm: 56 URLs ready" and "Starting MCP server...")*

## Phase 5: Update Your Agent

Now that the scraping server is permanently alive in the cloud, you don't need to run `mcp_server.py` on your local Windows machine anymore!

Simply go to the machine/terminal where your AI agent (`chat.py` or your API) will be running, and set the environment variable to your shiny new AWS server:

```powershell
# If running locally on Windows:
$env:MCP_SERVER_URL="http://<YOUR-EC2-IP>:8080/sse"

# If putting this in your .env file:
# MCP_SERVER_URL=http://<YOUR-EC2-IP>:8080/sse

python chat.py
```

### You are officially live! 🚀
Your AI will now instantly reach out to your AWS EC2 instance, which securely holds the zero-latency cache of all 14 Caribbean countries!
