#!/usr/bin/env bash
# One-time Ubuntu setup: installs Docker Engine + Docker Compose plugin.
# Run once on a fresh Ubuntu machine, then log out and back in.
set -e

echo "Installing Docker Engine..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin git

sudo usermod -aG docker "$USER"

echo ""
echo "Done. Log out and back in for the docker group to take effect."
echo ""
echo "Then, to deploy Alfred:"
echo "  cp .env.example .env   # fill in your API keys"
echo "  ./deploy.sh"
