#!/usr/bin/env sh

# First, create a custom SSM document with your script
# Alternatively, upload your script to S3 and reference it in the SSM document.

# Example command to run a script stored in an S3 bucket


cat <<EOF > aws.conf
[profile llm-rnd-sso]
sso_start_url = https://d-926773f8fe.awsapps.com/start
sso_region = us-west-2
sso_account_id = 424192958150
sso_role_name = LLMUser
region = us-west-2

EOF

export AWS_CONFIG_FILE=aws.conf

export AWS_PROFILE="llm-rnd-sso"

/usr/local/bin/aws sso login


aws ssm send-command \
    --targets "Key=tag:Name,Values=llm-apps" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["#!/bin/bash", "sudo /root/plur-rfp-tracker/linux-scripts/sync.sh"]'
