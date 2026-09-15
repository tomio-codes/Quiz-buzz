#pragma once

#include <stdint.h>

static const uint32_t BUZZ_MAGIC = 0x42555A5A;
static const uint8_t WIFI_CHANNEL = 1;
static const uint8_t TEAM_COUNT = 3;
static const uint8_t PKT_BUZZ = 1;
static const uint8_t PKT_HELLO = 2;
static const uint8_t PKT_LOCK = 3;
static const uint8_t PKT_UNLOCK = 4;
static const uint32_t HELLO_INTERVAL_MS = 1000;
static const uint32_t HELLO_STAGGER_MS = 300;
static const uint32_t LINK_TIMEOUT_MS = 10000;
static const uint8_t BROADCAST_ADDR[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

struct RadioPacket {
  uint32_t magic;
  uint8_t kind;
  uint8_t team_id;
  uint32_t seq;
} __attribute__((packed));
