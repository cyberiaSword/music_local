// ==UserScript==
// @name         YT Music Local Bridge
// @namespace    yt-music-local
// @version      3.0
// @description  Передаёт данные о текущем треке YouTube на локальный WebSocket-сервер
// @author       cyberiaSword
// @match        https://www.youtube.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    let ws = null;
    let reconnectTimer = null;
    let lastReportedId = null;

    // ============================================================
    // WebSocket
    // ============================================================
    function connect() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        ws = new WebSocket('ws://127.0.0.1:8765');

        ws.onopen = () => {
            console.log('[YT-Bridge] Подключено к локальному серверу');
        };

        ws.onclose = () => {
            console.log('[YT-Bridge] Соединение разорвано, переподключение через 3 сек');
            scheduleReconnect();
        };

        ws.onerror = () => {
            console.warn('[YT-Bridge] Ошибка WebSocket');
        };
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, 3000);
    }

    // ============================================================
    // Извлечение информации о видео
    // ============================================================
    function getVideoInfo() {
        const video = document.querySelector('video');
        if (!video) return null;

        const videoId = new URLSearchParams(window.location.search).get('v');
        if (!videoId) return null;

        // Заголовок — из мета-тега или из title
        let title = document.title.replace(' - YouTube', '').trim();
        const metaTitle = document.querySelector('meta[name="title"]');
        if (metaTitle && metaTitle.content) {
            title = metaTitle.content;
        }

        // Канал
        let channel = '';
        const channelEl = document.querySelector('#owner #channel-name a, ytd-channel-name a');
        if (channelEl) channel = channelEl.textContent.trim();

        return {
            videoId: videoId,
            title: title,
            channel: channel,
            url: window.location.href,
            duration: isFinite(video.duration) ? Math.floor(video.duration) : 0,
            isPlaying: !video.paused,
            currentTime: video.currentTime
        };
    }

    // ============================================================
    // Отправка
    // ============================================================
    function sendState(action) {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            connect();
            return;
        }

        const info = getVideoInfo();
        if (!info) return;

        const payload = { action, ...info, timestamp: Date.now() };
        console.log('[YT-Bridge] Отправляю:', action, '→', info.title);
        ws.send(JSON.stringify(payload));
    }

    // ============================================================
    // Слушатели на <video>
    // ============================================================
    function attachListeners() {
        const video = document.querySelector('video');
        if (!video) return false;
        if (video._ytBridgeAttached) return true;
        video._ytBridgeAttached = true;

        video.addEventListener('playing', () => {
            console.log('[YT-Bridge] Событие playing');
            sendState('play');
        });

        video.addEventListener('pause', () => sendState('pause'));
        video.addEventListener('ended', () => sendState('ended'));

        // Резервный триггер на случай, если playing не сработал
        video.addEventListener('timeupdate', () => {
            if (video.currentTime < 1) return;
            const videoId = new URLSearchParams(window.location.search).get('v');
            if (!videoId || videoId === lastReportedId) return;
            lastReportedId = videoId;
            console.log('[YT-Bridge] Fallback timeupdate');
            sendState('play');
        });

        console.log('[YT-Bridge] Слушатели подключены');
        return true;
    }

    // Периодически проверяем наличие <video> (SPA-навигация)
    setInterval(() => {
        const video = document.querySelector('video');
        if (video && !video._ytBridgeAttached) {
            attachListeners();
        }
    }, 3000);

    window.addEventListener('yt-navigate-finish', () => {
        lastReportedId = null;
        setTimeout(attachListeners, 500);
    });

    // ============================================================
    // Запуск
    // ============================================================
    connect();
    attachListeners();
    console.log('[YT-Bridge] Инициализирован v3.0');

})();