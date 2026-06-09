#!/usr/bin/env sh
set -e

eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
git -C /root/plur-rfp-tracker/ pull origin

cd /root/plur-rfp-tracker

docker-compose build
docker-compose stop
docker-compose up -d
