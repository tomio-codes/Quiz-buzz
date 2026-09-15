#pragma once

#include <Arduino.h>

static const uint8_t PIN_BUTTON = 4;
static const uint8_t PIN_BOOT = 9;
static const uint8_t PIN_LED = 8;
static const uint8_t PIN_STATUS = 3;
static const bool LED_ACTIVE_LOW = true;
static const uint32_t DEBOUNCE_MS = 40;

inline void ledWrite(bool on) {
  digitalWrite(PIN_LED, LED_ACTIVE_LOW ? !on : on);
}

class DebouncedButton {
 public:
  explicit DebouncedButton(uint8_t pin)
      : pin_(pin), last_stable_(true), last_read_(true), last_change_ms_(0) {}

  void begin() {
    pinMode(pin_, INPUT_PULLUP);
    last_stable_ = digitalRead(pin_);
    last_read_ = last_stable_;
  }

  bool pressed() {
    const bool now = digitalRead(pin_);
    const uint32_t now_ms = millis();
    if (now != last_read_) {
      last_read_ = now;
      last_change_ms_ = now_ms;
    }
    if ((now_ms - last_change_ms_) > DEBOUNCE_MS && now != last_stable_) {
      last_stable_ = now;
      return last_stable_ == LOW;
    }
    return false;
  }

 private:
  uint8_t pin_;
  bool last_stable_;
  bool last_read_;
  uint32_t last_change_ms_;
};
