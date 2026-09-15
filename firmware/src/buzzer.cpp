#include <Arduino.h>
#include <WiFi.h>
#include <cstring>
#include <esp_idf_version.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "hardware.h"
#include "protocol.h"

#ifndef TEAM_ID
#error TEAM_ID must be set to 1, 2 or 3
#endif

static DebouncedButton buzz_button(PIN_BUTTON);
static DebouncedButton boot_button(PIN_BOOT);
static uint32_t seq = 0;
static uint32_t led_until_ms = 0;
static uint32_t last_hello_ms = 0;

static void statusWrite(bool on) { digitalWrite(PIN_STATUS, on ? HIGH : LOW); }

static void send_packet(uint8_t kind) {
  RadioPacket packet;
  packet.magic = BUZZ_MAGIC;
  packet.kind = kind;
  packet.team_id = TEAM_ID;
  packet.seq = ++seq;
  esp_now_send(BROADCAST_ADDR, reinterpret_cast<uint8_t *>(&packet), sizeof(packet));
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
  if (packet.magic != BUZZ_MAGIC) {
    return;
  }
  if (packet.kind == PKT_LOCK) {
    statusWrite(packet.team_id == TEAM_ID);
    return;
  }
  if (packet.kind == PKT_UNLOCK) {
    statusWrite(false);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_STATUS, OUTPUT);
  ledWrite(false);
  statusWrite(false);
  buzz_button.begin();
  boot_button.begin();

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    while (true) {
      delay(1000);
    }
  }

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST_ADDR, 6);
  peer.channel = WIFI_CHANNEL;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    while (true) {
      delay(1000);
    }
  }

  if (esp_now_register_recv_cb(on_recv) != ESP_OK) {
    while (true) {
      delay(1000);
    }
  }

  Serial.print("BUZZER team=");
  Serial.println(TEAM_ID);
  last_hello_ms = millis() - HELLO_INTERVAL_MS + (TEAM_ID - 1) * HELLO_STAGGER_MS;
}

void loop() {
  const uint32_t now = millis();
  if (buzz_button.pressed() || boot_button.pressed()) {
    send_packet(PKT_BUZZ);
    led_until_ms = now + 250;
  }
  if (now - last_hello_ms >= HELLO_INTERVAL_MS) {
    last_hello_ms = now;
    send_packet(PKT_HELLO);
  }
  ledWrite(now < led_until_ms);
}
