#pragma once

#include <Arduino.h>

static const uint8_t PIN_BUTTON = 4;
static const uint8_t PIN_BOOT = 9;
static const uint8_t PIN_LED = 8;
static const bool LED_ACTIVE_LOW = true;
static const uint32_t DEBOUNCE_MS = 80;
static const uint32_t HOLD_MS = 50;

inline void ledWrite(bool on) {
  digitalWrite(PIN_LED, LED_ACTIVE_LOW ? !on : on);
}

class DebouncedButton {
 public:
  explicit DebouncedButton(uint8_t pin) : pin_(pin) {}

  void begin() {
    pinMode(pin_, INPUT_PULLUP);
    last_read_ = digitalRead(pin_);
    edge_ms_ = millis();
    low_since_ms_ = 0;
    fired_ = false;
  }

  bool pressed() {
    const bool now = digitalRead(pin_);
    const uint32_t t = millis();
    if (now != last_read_) {
      last_read_ = now;
      edge_ms_ = t;
      low_since_ms_ = 0;
      fired_ = false;
    }
    if ((t - edge_ms_) < DEBOUNCE_MS) {
      return false;
    }
    if (now == HIGH) {
      low_since_ms_ = 0;
      fired_ = false;
      return false;
    }
    if (low_since_ms_ == 0) {
      low_since_ms_ = t;
      return false;
    }
    if (fired_ || (t - low_since_ms_) < HOLD_MS) {
      return false;
    }
    fired_ = true;
    return true;
  }

 private:
  uint8_t pin_;
  bool last_read_ = true;
  bool fired_ = false;
  uint32_t edge_ms_ = 0;
  uint32_t low_since_ms_ = 0;
};
