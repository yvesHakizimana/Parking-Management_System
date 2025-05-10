#include <EEPROM.h>
void setup() {
  EEPROM.update(50, 0);  // Reset failed attempts
  EEPROM.put(54, 0UL);   // Clear lockoutEnd (unsigned long)
  Serial.println("🔓 System unlocked");
}
void loop() {}