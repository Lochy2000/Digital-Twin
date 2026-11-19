#!/bin/sh
# dt-broker start-up (compose.yml runs this instead of the image's default).
# 1. Builds the password file from .env, hashed with mosquitto_passwd
#    (https://manpages.ubuntu.com/manpages/jammy/man1/mosquitto_passwd.1.html). Rebuilt at
#    every start, so changing .env + "docker compose up -d" is all it takes.
#      services: ingestion_gateway, historian, engineer (each its own password)
#      devices:  every name in MQTT_DEVICES, sharing MQTT_DEVICE_PASSWORD for now
#                (a real device should get its own line and password before any site use)
# 2. Copies acl.conf next to it, so both files belong to Mosquitto's user and nobody else.
# 3. Starts Mosquitto (it switches from root to its own "mosquitto" user by itself).
set -e
: "${MQTT_GATEWAY_PASSWORD:?missing}" "${MQTT_HISTORIAN_PASSWORD:?missing}"
: "${MQTT_DEVICE_PASSWORD:?missing}" "${MQTT_ENGINEER_PASSWORD:?missing}"

auth=/mosquitto/auth
mkdir -p "$auth"
rm -f "$auth/passwords"
mosquitto_passwd -c -b "$auth/passwords" ingestion_gateway "$MQTT_GATEWAY_PASSWORD"
mosquitto_passwd -b "$auth/passwords" historian "$MQTT_HISTORIAN_PASSWORD"
mosquitto_passwd -b "$auth/passwords" engineer "$MQTT_ENGINEER_PASSWORD"
for device in ${MQTT_DEVICES:-}; do
  mosquitto_passwd -b "$auth/passwords" "$device" "$MQTT_DEVICE_PASSWORD"
done
cp /mosquitto/broker/acl.conf "$auth/acl"

chown -R mosquitto:mosquitto "$auth" /mosquitto/data
chmod 700 "$auth"
chmod 600 "$auth/passwords" "$auth/acl"
echo "start.sh: logins ready (devices: ${MQTT_DEVICES:-none}), access rules ready"
exec mosquitto -c /mosquitto/config/mosquitto.conf
