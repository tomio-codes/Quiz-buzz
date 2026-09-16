/*
  Quiz Buzz — přijímač u počítače moderátora (ESP32-C3)

  Arduino IDE:
    Deska: ESP32C3 Dev Module
    USB CDC On Boot: Enabled
    Flash Mode: DIO
*/

#include <WiFi.h>
#include <cstring>
#include <esp_idf_version.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "hardware.h"
#include "protocol.h"

static volatile uint8_t locked_team = 0;
static volatile uint32_t last_seen_ms[TEAM_COUNT + 1];
static volatile uint8_t seen_mask = 0;
static volatile uint8_t pending_alive[TEAM_COUNT + 1] = {};
static volatile uint32_t pending_alive_seq[TEAM_COUNT + 1] = {};
static volatile uint8_t pending_buzz_report = 0;
static DebouncedButton reset_button(PIN_BUTTON);
static DebouncedButton boot_button(PIN_BOOT);

static bool valid_team(uint8_t team_id) { return team_id >= 1 && team_id <= TEAM_COUNT; }

static void mark_seen(uint8_t team_id) {
  last_seen_ms[team_id] = millis();
  seen_mask |= static_cast<uint8_t>(1 << team_id);
}

static void ensure_broadcast_peer() {
  static bool added = false;
  if (added) {
    return;
  }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST_ADDR, 6);
  peer.channel = WIFI_CHANNEL;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) == ESP_OK) {
    added = true;
  }
}

static void broadcast_round(uint8_t kind, uint8_t team_id) {
  ensure_broadcast_peer();
  RadioPacket packet = {};
  packet.magic = BUZZ_MAGIC;
  packet.kind = kind;
  packet.team_id = team_id;
  for (uint8_t i = 0; i < 3; i++) {
    esp_now_send(BROADCAST_ADDR, reinterpret_cast<uint8_t *>(&packet), sizeof(packet));
    delay(20);
  }
}

static void unlock() {
  locked_team = 0;
  broadcast_round(PKT_UNLOCK, 0);
}

static void flush_pending_alive() {
  for (uint8_t team = 1; team <= TEAM_COUNT; team++) {
    if (!pending_alive[team]) {
      continue;
    }
    pending_alive[team] = 0;
    Serial.print("ALIVE ");
    Serial.print(team);
    Serial.print(" ");
    Serial.println(pending_alive_seq[team]);
  }
}

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
static void on_recv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  (void)info;
#else
static void on_recv(const uint8_t *mac, const uint8_t *data, int len) {
  (void)mac;
#endif
  if (len != (int)sizeof(RadioPacket)) {
    return;
  }

  RadioPacket packet;
  memcpy(&packet, data, sizeof(packet));
  if (packet.magic != BUZZ_MAGIC || !valid_team(packet.team_id)) {
    return;
  }
  if (packet.kind != PKT_HELLO && packet.kind != PKT_BUZZ) {
    return;
  }

  mark_seen(packet.team_id);
  if (packet.kind == PKT_HELLO) {
    pending_alive_seq[packet.team_id] = packet.seq;
    pending_alive[packet.team_id] = 1;
  }
  if (packet.kind == PKT_BUZZ) {
    pending_buzz_report = packet.team_id;
    if (locked_team == 0) {
      locked_team = packet.team_id;
    }
  }
}

static void report_links() {
  static bool linked[TEAM_COUNT + 1] = {};
  const uint32_t now = millis();
  const uint8_t seen = seen_mask;
  for (uint8_t team = 1; team <= TEAM_COUNT; team++) {
    const bool alive =
        (seen & (1 << team)) != 0 && (now - last_seen_ms[team]) < HEARTBEAT_PAUSE_MS;
    if (alive) {
      linked[team] = true;
      continue;
    }
    if (linked[team]) {
      linked[team] = false;
      Serial.print("UNLINK ");
      Serial.println(team);
      Serial.flush();
    }
  }
}

static void handle_serial_line(const String &line) {
  if (line == "RESET") {
    unlock();
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);
  pinMode(PIN_LED, OUTPUT);
  ledWrite(false);
  reset_button.begin();
  boot_button.begin();

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ERROR esp_now");
    while (true) {
      delay(1000);
    }
  }

  if (esp_now_register_recv_cb(on_recv) != ESP_OK) {
    Serial.println("ERROR recv_cb");
    while (true) {
      delay(1000);
    }
  }

  Serial.println("READY");
}

void loop() {
  static uint8_t last_reported = 0;

  while (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    handle_serial_line(line);
  }

  const uint8_t team = locked_team;

  flush_pending_alive();

  if (pending_buzz_report != 0) {
    Serial.print("BUZZ ");
    Serial.println(pending_buzz_report);
    pending_buzz_report = 0;
  }

  if (team != 0 && team != last_reported) {
    broadcast_round(PKT_LOCK, team);
    last_reported = team;
  }
  if (team == 0 && last_reported != 0) {
    last_reported = 0;
  }

  report_links();
  ledWrite(team != 0);

  if (reset_button.pressed() || boot_button.pressed()) {
    unlock();
    Serial.println("RESET");
  }
}
