// ============================================================
// ESP32-CAM → Web Service en Render
// Placa: AI-Thinker ESP32-CAM
// Librerías requeridas: ArduinoJson (instalar desde Library Manager)
// ============================================================

#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// ------------------------------------------------------------
// CONFIGURACIÓN — edita estos valores
// ------------------------------------------------------------
const char* WIFI_SSID      = "TU_WIFI_SSID";
const char* WIFI_PASSWORD  = "TU_WIFI_PASSWORD";
const char* SERVER_URL     = "https://web-service-en-render.onrender.com/upload";
const int   INTERVALO_MS   = 10000;  // ms entre capturas (10 segundos)
// ------------------------------------------------------------

// Pines AI-Thinker ESP32-CAM
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define LED_FLASH          4  // Flash LED integrado

void initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // QVGA (320x240) — bueno para upload rápido
  config.frame_size   = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;   // 0-63, menor = mejor calidad
  config.fb_count     = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] Error init: 0x%x\n", err);
    Serial.println("[CAM] Reiniciando...");
    delay(3000);
    ESP.restart();
  }
  Serial.println("[CAM] Inicializada OK");
}

void connectWiFi() {
  Serial.printf("[WiFi] Conectando a %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int intentos = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++intentos > 30) {
      Serial.println("\n[WiFi] Timeout. Reiniciando...");
      ESP.restart();
    }
  }
  Serial.printf("\n[WiFi] Conectado. IP: %s\n", WiFi.localIP().toString().c_str());
}

void takeAndUpload() {
  // Descarta frame anterior (puede tener buffer viejo)
  camera_fb_t* fb = esp_camera_fb_get();
  esp_camera_fb_return(fb);
  delay(100);

  // Captura real
  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] Error capturando imagen");
    return;
  }
  Serial.printf("[CAM] Imagen capturada: %u bytes\n", fb->len);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Sin conexión, reconectando...");
    connectWiFi();
  }

  WiFiClientSecure client;
  client.setInsecure();  // Sin verificación de certificado (suficiente para prototipo)

  HTTPClient https;
  if (!https.begin(client, SERVER_URL)) {
    Serial.println("[HTTP] No se pudo iniciar conexión");
    esp_camera_fb_return(fb);
    return;
  }

  // Construir multipart/form-data
  String boundary = "ESP32BOUNDARY";
  String head = "--" + boundary + "\r\n"
                "Content-Disposition: form-data; name=\"file\"; filename=\"foto.jpg\"\r\n"
                "Content-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";

  int totalLen = head.length() + fb->len + tail.length();
  uint8_t* body = (uint8_t*)malloc(totalLen);
  if (!body) {
    Serial.println("[HTTP] Sin memoria para el buffer");
    esp_camera_fb_return(fb);
    https.end();
    return;
  }
  memcpy(body,                            head.c_str(), head.length());
  memcpy(body + head.length(),            fb->buf,      fb->len);
  memcpy(body + head.length() + fb->len, tail.c_str(), tail.length());

  https.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);

  Serial.println("[HTTP] Enviando imagen...");
  int httpCode = https.POST(body, totalLen);
  free(body);
  esp_camera_fb_return(fb);

  if (httpCode == 200) {
    String payload = https.getString();
    Serial.println("[HTTP] Respuesta: " + payload);

    // Parsear JSON
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, payload);
    if (!error) {
      bool qr      = doc["qr_detectado"]     | false;
      bool rostro  = doc["rostro_detectado"] | false;
      int  nRostro = doc["rostro_cantidad"]  | 0;
      const char* qrData = doc["qr_data"]   | "";

      Serial.printf("[RESULT] QR: %s", qr ? "SI" : "NO");
      if (qr && strlen(qrData) > 0) Serial.printf(" → %s", qrData);
      Serial.println();
      Serial.printf("[RESULT] Rostro: %s", rostro ? "SI" : "NO");
      if (rostro) Serial.printf(" (%d detectados)", nRostro);
      Serial.println();
    }
  } else {
    Serial.printf("[HTTP] Error: %d — %s\n", httpCode, https.errorToString(httpCode).c_str());
  }

  https.end();
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== ESP32-CAM Sistema IoT ===");

  pinMode(LED_FLASH, OUTPUT);
  digitalWrite(LED_FLASH, LOW);

  initCamera();
  connectWiFi();

  Serial.println("[OK] Listo. Iniciando capturas...");
}

void loop() {
  takeAndUpload();
  delay(INTERVALO_MS);
}
