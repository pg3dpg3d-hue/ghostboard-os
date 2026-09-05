// ---------------------------------------------------------------------------
//  wifiscan.cpp — reconnaissance Wi-Fi passive.
//
//  Logique de scan/affichage reprise telle quelle du code fourni. Seules
//  additions pour l'intégration GHOSTBOARD :
//    - wifiscanLoop() renvoie true pour rendre la main au menu (LEFT sur la
//      liste) ; LEFT en vue détail revient à la liste comme avant ;
//    - réinitialisation de l'état à chaque entrée (le module est ré-entrant
//      depuis le menu) ;
//    - en-tête et LED aux couleurs de la charte.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "wifiscan.h"

namespace WifiScan {

int currentIndex = 0;
int listStartIndex = 0;
bool isDetailView = false;
unsigned long scan_StartTime = 0;
const unsigned long scanTimeout = 2000;
bool isScanComplete = false;

unsigned long lastButtonPress = 0;
unsigned long debounceTime = 200;

void wifiscanSetup() {
  u8g2.setFont(u8g2_font_6x10_tr);

  // Ré-entrée depuis le menu : on repart d'un état propre.
  currentIndex = 0;
  listStartIndex = 0;
  isDetailView = false;
  isScanComplete = false;

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  for (int cycle = 0; cycle < 3; cycle++) {
    for (int i = 0; i < 3; i++) {
      u8g2.clearBuffer();
      u8g2.setFont(u8g2_font_6x10_tr);
      u8g2.drawStr(0, 10, "Scanning WiFi");

      String dots = "";
      for (int j = 0; j <= i; j++) {
        dots += ".";
        setNeoPixelColour("scan");
      }
      setNeoPixelColour("0");

      u8g2.drawStr(80, 10, dots.c_str());

      u8g2.sendBuffer();
      delay(300);
    }
  }

  scan_StartTime = millis();
  isScanComplete = false;
}

bool wifiscanLoop() {
  unsigned long currentMillis = millis();

  if (!isScanComplete && currentMillis - scan_StartTime < scanTimeout) {
    int foundNetworks = WiFi.scanNetworks();
    if (foundNetworks >= 0) {
      isScanComplete = true;
    }
  }

  if (currentMillis - lastButtonPress > debounceTime) {
    if (digitalRead(BUTTON_UP_PIN) == LOW) {
      if (currentIndex > 0) {
        currentIndex--;
        if (currentIndex < listStartIndex) {
          listStartIndex--;
        }
      }
      lastButtonPress = currentMillis;
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
      if (currentIndex < WiFi.scanComplete() - 1) {
        currentIndex++;
        if (currentIndex >= listStartIndex + 5) {
          listStartIndex++;
        }
      }
      lastButtonPress = currentMillis;
    } else if (digitalRead(BTN_PIN_RIGHT) == LOW) {
      isDetailView = true;
      lastButtonPress = currentMillis;
    } else if (digitalRead(BTN_PIN_LEFT) == LOW && !isDetailView) {
      // LEFT sur la liste : retour au menu principal.
      lastButtonPress = currentMillis;
      setNeoPixelColour("0");
      return true;
    }
  }

  if (!isDetailView && isScanComplete) {
    u8g2.clearBuffer();
    gbHeader("Wi-Fi Networks");

    int networkCount = WiFi.scanComplete();
    for (int i = 0; i < 5; i++) {
      int currentNetworkIndex = i + listStartIndex;
      if (currentNetworkIndex >= networkCount) break;

      String networkName = WiFi.SSID(currentNetworkIndex);
      int rssi = WiFi.RSSI(currentNetworkIndex);

      String networkInfo = networkName.substring(0, 7);
      String networkrssi = " | RSSI " + String(rssi);
      u8g2.setFont(u8g2_font_6x10_tr);

      if (currentNetworkIndex == currentIndex) {
        u8g2.drawStr(0, 23 + i * 10, ">");
      }
      u8g2.drawStr(10, 23 + i * 10, networkInfo.c_str());
      u8g2.drawStr(50, 23 + i * 10, networkrssi.c_str());
    }
    u8g2.sendBuffer();
  }

  if (isDetailView) {
    String networkName = WiFi.SSID(currentIndex);
    String networkBSSID = WiFi.BSSIDstr(currentIndex);
    int rssi = WiFi.RSSI(currentIndex);
    int channel = WiFi.channel(currentIndex);

    u8g2.clearBuffer();
    gbHeader("Network Details");

    u8g2.setFont(u8g2_font_5x8_tr);
    String name = "SSID: " + networkName;
    String bssid = "BSSID: " + networkBSSID;
    String signal = "RSSI: " + String(rssi);
    String ch = "Channel: " + String(channel);

    u8g2.drawStr(0, 24, name.c_str());
    u8g2.drawStr(0, 34, bssid.c_str());
    u8g2.drawStr(0, 44, signal.c_str());
    u8g2.drawStr(0, 54, ch.c_str());
    u8g2.drawStr(0, 63, "LEFT: back");
    u8g2.sendBuffer();

    if (digitalRead(BTN_PIN_LEFT) == LOW) {
      isDetailView = false;
      lastButtonPress = currentMillis;
    }
  }

  return false;
}

}  // namespace WifiScan
