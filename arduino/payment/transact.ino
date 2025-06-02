#include <SPI.h>
#include <MFRC522.h>
#include <SoftwareSerial.h>

#define RST_PIN 9
#define SS_PIN 10
#define BALANCE_BLOCK 6  // Changed from 5 to avoid trailer block conflicts
#define PLATE_BLOCK 5


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

  Serial.println(F("RFID Transact Ready."));
  Serial.println(F("Present a card to process payment."));
}

void loop() {
  if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) {
    delay(100);
    return;
  }

  Serial.println(F("✅ Card detected."));

  String plate = readBlock(PLATE_BLOCK);
  String balance = readBlock(BALANCE_BLOCK);

  if (plate.length() > 0 && balance.length() > 0) {
    Serial.print(F("PROCESS_PAYMENT:"));
    Serial.print(plate);
    Serial.print(",");
    Serial.println(balance);

    // Wait for response from Python script
    while (Serial.available() == 0) {}
    String response = Serial.readStringUntil('\n');
    response.trim();

    if (response.startsWith("NEW_BALANCE:")) {
      String newBalance = response.substring(12);
      if (writeBlock(BALANCE_BLOCK, newBalance)) {
        Serial.println(F("✅ Balance updated"));
      } else {
        Serial.println(F("❌ Failed to update balance"));
      }
    } else if (response.startsWith("ERROR:")) {
      Serial.print(F("❌ Payment failed: "));
      Serial.println(response.substring(6));
    } else {
      Serial.println(F("❌ Unknown response from script"));
    }
  } else {
    Serial.println(F("❌ Failed to read card data"));
  }

  stopCard();
  delay(500);
}

String readBlock(byte block) {
  byte buffer[18];
  byte size = sizeof(buffer);

  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Auth failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return "";
  }

  card_status = mfrc522.MIFARE_Read(block, buffer, &size);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Read failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return "";
  }

  String value = "";
  for (uint8_t i = 0; i < 16; i++) {
    if (buffer[i] == 0 || buffer[i] == ' ') break;
    value += (char)buffer[i];
  }
  value.trim();
  return value;
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