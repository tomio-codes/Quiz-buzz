#pragma once

#include <Arduino.h>

static const uint8_t PIN_BUTTON = 4;
static const uint8_t PIN_LED = 8;
static const uint8_t PIN_STATUS = 3;
static const bool LED_ACTIVE_LOW = true;
static const uint32_t DEBOUNCE_MS = 30;
static const uint32_t BUZZ_COOLDOWN_MS = 250;

inline void ledWrite(bool on) {
  digitalWrite(PIN_LED, LED_ACTIVE_LOW ? !on : on);
}

class DebouncedButton {
 public:
  explicit DebouncedButton(uint8_t pin) : pin_(pin) {}

  void begin() {
    pinMode(pin_, INPUT_PULLUP);
    last_read_ = digitalRead(pin_);
    last_stable_ = last_read_;
    edge_ms_ = millis();
  }

  bool pressed() {
    const bool now = digitalRead(pin_);
    const uint32_t t = millis();
    if (now != last_read_) {
      last_read_ = now;
      edge_ms_ = t;
    }
    if ((t - edge_ms_) < DEBOUNCE_MS) {
      return false;
    }
    if (now == LOW && last_stable_ == HIGH) {
      last_stable_ = LOW;
      return true;
    }
    if (now == HIGH) {
      last_stable_ = HIGH;
    }
    return false;
  }

 private:
  uint8_t pin_;
  bool last_read_ = true;
  bool last_stable_ = true;
  uint32_t edge_ms_ = 0;
};
