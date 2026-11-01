#!/bin/sh
# Mosquitto start-up for v0.1 (docker-compose.yml runs this instead of the image's default).
# 1. Builds the password file from the MQTT_* passwords in .env, hashed with mosquitto_passwd
#    (https://manpages.ubuntu.com/manpages/jammy/man1/mosquitto_passwd.1.html). Rebuilt at every
#    start, so changing a password in .env + "docker compose up -d" is all it takes.
# 2. Copies broker/acl.conf next to it, so both files belong to Mosquitto's user and nobody else.
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
# Test devices share one password for now. A real device gets its own line and password.
for device in acme_hvac_0001 site4_hvac_01 tasmota_zone1; do
  mosquitto_passwd -b "$auth/passwords" "$device" "$MQTT_DEVICE_PASSWORD"
done
cp /mosquitto/broker/acl.conf "$auth/acl"

chown -R mosquitto:mosquitto "$auth" /mosquitto/data
chmod 700 "$auth"
chmod 600 "$auth/passwords" "$auth/acl"
echo "start.sh: password file and access rules ready"
exec mosquitto -c /mosquitto/config/mosquitto.conf
