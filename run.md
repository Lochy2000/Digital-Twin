

to inspect output 

cd C:\Users\User\OneDrive\Desktop\projects\Bontaic\botanicEnergy\virtual-DT\v0.1

docker compose exec mosquitto mosquitto_sub -v -t "raw/#" -t "dt/v1/#"


docker compose logs -f gateway


see both 

cd C:\Users\User\OneDrive\Desktop\projects\Bontaic\botanicEnergy\virtual-DT\v0.1

docker compose --profile acme down

$env:GATEWAY_ENABLED="acme_hvac_0001=off,site4_hvac_01=on"
docker compose --profile borealis up --build

what this shows raw/borealis/site4_hvac_01/data- Borealis’s original format
dt/v1/telemetry/site1/unit1/zone_air_temp- normalised temperature
dt/v1/telemetry/site1/unit1/mode_status- normalised operating mode
dt/v1/quarantine/borealis — humidity, intentionally unmapped for now


docker compose exec mosquitto mosquitto_sub -v `
  -t "raw/#" `
  -t "dt/v1/#"



show all four formats

cd services\ingestion-gateway
python -m gateway.demo