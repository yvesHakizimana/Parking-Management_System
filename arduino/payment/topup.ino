#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 9
#define SS_PIN 10
#define BALANCE_BLOCK 6  // Changed from 5 to avoid trailer block conflicts
#define PLATE_BLOCK 5
#define MAX_PLATE_LENGTH 7
#define MAX_BALANCE_DIGITS 10

MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

void setup() {
  Serial.begin(9600);
  SPI.begin();
  mfrc522.PCD_Init();

  for (byte i = 0; i < 6; i++) {
    key.keyByte[i] = 0xFF;
  }

  Serial.println(F("RFID Top-Up Ready."));
  Serial.println(F("> Enter data in format: PLATE|BALANCE (e.g., RAB123A|1000)"));
}

void loop() {
  if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) {
    delay(100);
    return;
  }

  Serial.println(F("✅ Card detected. Enter PLATE|BALANCE:"));
  while (Serial.available() == 0) {}

  String input = Serial.readStringUntil('\n');
  input.trim();

  int separatorIndex = input.indexOf('|');
  if (separatorIndex <= 0 || separatorIndex == input.length() - 1) {
    Serial.println(F("❌ Invalid format. Use PLATE|BALANCE"));
    stopCard();
    return;
  }

  String plate = input.substring(0, separatorIndex);
  String balance = input.substring(separatorIndex + 1);
  plate.trim();
  balance.trim();

  if (!isValidRwandanPlate(plate)) {
    Serial.println(F("❌ Invalid plate format. Must be 3 letters, 3 digits, 1 letter (e.g., RAB123A)"));
    stopCard();
    return;
  }

  if (!isValidAmount(balance)) {
    Serial.println(F("❌ Invalid balance. Must be digits only, max 10 digits"));
    stopCard();
    return;
  }


  if (!writeBlock(PLATE_BLOCK, plate)) {
    Serial.println(F("❌ Failed to write plate"));
    stopCard();
    return;
  }

  if (!writeBlock(BALANCE_BLOCK, balance)) {
    Serial.println(F("❌ Failed to write balance"));
    stopCard();
    return;
  }

  Serial.println(F("✅ Success: Plate and balance written"));
  Serial.print(F("🚗 Plate: "));
  Serial.println(plate);
  Serial.print(F("💰 Balance: "));
  Serial.println(balance);
  stopCard();
  delay(500);
}

bool isValidRwandanPlate(String plate) {
  if (plate.length() != MAX_PLATE_LENGTH) return false;
  if (!isAlpha(plate[0]) || !isAlpha(plate[1]) || !isAlpha(plate[2])) return false;
  if (!isDigit(plate[3]) || !isDigit(plate[4]) || !isDigit(plate[5])) return false;
  if (!isAlpha(plate[6])) return false;
  return true;
}

bool isValidAmount(String amount) {
  if (amount.length() == 0 || amount.length() > MAX_BALANCE_DIGITS) return false;
  for (int i = 0; i < amount.length(); i++) {
    if (!isDigit(amount[i])) return false;
  }
  return true;
}

bool writeBlock(byte block, String data) {
  byte buffer[16];
  if (data.length() > 16) data = data.substring(0, 16);
  data.toCharArray((char *)buffer, 16);
  for (byte i = data.length(); i < 16; i++) buffer[i] = ' ';

  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Auth failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return false;
  }

  card_status = mfrc522.MIFARE_Write(block, buffer, 16);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Write failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return false;
  }

  return true;
}

void stopCard() {
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
}

