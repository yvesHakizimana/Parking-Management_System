#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 9
#define SS_PIN 10

MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

// Block numbers where data is stored
#define BALANCE_BLOCK 4
#define PLATE_BLOCK 5

void setup() {
  Serial.begin(9600);
  SPI.begin();
  mfrc522.PCD_Init();

  // Initialize authentication key
  for (byte i = 0; i < 6; i++) {
    key.keyByte[i] = 0xFF;
  }

  Serial.println(F("RFID PAYMENT SYSTEM READY"));
  Serial.println(F("SCAN CARD TO BEGIN TRANSACTION"));
}

void loop() {
  if (!mfrc522.PICC_IsNewCardPresent()) {
    return;
  }

  if (!mfrc522.PICC_ReadCardSerial()) {
    return;
  }

  // Read plate number and balance
  String plateNumber = readBlock(PLATE_BLOCK);
  String balanceStr = readBlock(BALANCE_BLOCK);

  if (plateNumber.length() == 0 || balanceStr.length() == 0) {
    Serial.println("ERROR: Failed to read card data");
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    return;
  }

  // Convert balance to integer
  int balance = balanceStr.toInt();

  // Check minimum balance
  if (balance < 500) {
    Serial.print("INSUFFICIENT_BALANCE:");
    Serial.println(balance);
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    return;
  }

  // Send data to Python for processing
  Serial.print("PROCESS_PAYMENT:");
  Serial.print(plateNumber);
  Serial.print(",");
  Serial.println(balance);

  // Wait for response from Python
  while (!Serial.available()) {
    delay(100);
  }

  // Read Python's response
  String response = Serial.readStringUntil('\n');
  response.trim();

  if (response.startsWith("NEW_BALANCE:")) {
    int newBalance = response.substring(12).toInt();

    // Update card balance
    if (writeBlock(BALANCE_BLOCK, String(newBalance))) {
      Serial.println("SUCCESS: Transaction completed");
    } else {
      Serial.println("ERROR: Failed to update card balance");
    }
  } else {
    Serial.print("ERROR: ");
    Serial.println(response);
  }

  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
  delay(1000);
}

String readBlock(byte blockNumber) {
  byte buffer[18];
  byte size = sizeof(buffer);

  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("Authentication failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return "";
  }

  card_status = mfrc522.MIFARE_Read(blockNumber, buffer, &size);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("Reading failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return "";
  }

  String value = "";
  for (uint8_t i = 0; i < 16; i++) {
    if (buffer[i] == 0) break;
    value += (char)buffer[i];
  }
  value.trim();

  return value;
}

bool writeBlock(byte blockNumber, String data) {
  byte buffer[16];

  // Convert string to byte array
  data.toCharArray((char *)buffer, 16);

  // Pad with spaces if needed
  for (byte i = data.length(); i < 16; i++) {
    buffer[i] = ' ';
  }

  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("Authentication failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return false;
  }

  card_status = mfrc522.MIFARE_Write(blockNumber, buffer, 16);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("Writing failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return false;
  }

  return true;
}
