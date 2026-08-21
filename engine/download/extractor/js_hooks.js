(function () {
    if (window.__STREAM_HOOKS_INSTALLED__) return;
    window.__STREAM_HOOKS_INSTALLED__ = true;

    window.__STREAM_LOGS__ = window.__STREAM_LOGS__ || [];

    var STREAM_KEYWORDS = ['.m3u8', '.mpd', '.mp4', '.webm', 'master', '/hls', '/engine/hls', 'index-v', '/secure/', 'playlist'];

    function _isStreamUrl(url) {
        if (!url || typeof url !== 'string') return false;
        var low = url.toLowerCase();
        if (low.startsWith('blob:') || low.startsWith('data:')) return false;
        for (var i = 0; i < STREAM_KEYWORDS.length; i++) {
            if (low.indexOf(STREAM_KEYWORDS[i]) !== -1) return true;
        }
        return false;
    }

    function _log(url, type, extra) {
        if (!_isStreamUrl(url)) return;
        var entry = {
            url: url,
            type: type,
            ts: Date.now(),
            extra: extra || null,
        };
        window.__STREAM_LOGS__.push(entry);
        try { console.debug('[STREAM_HOOK]', type, url.substring(0, 100)); } catch (e) {}
    }

    var _origFetch = window.fetch;
    window.fetch = function (input, init) {
        var url = (typeof input === 'string') ? input : (input && input.url) || '';
        _log(url, 'fetch');
        return _origFetch.apply(this, arguments);
    };

    var _origXHROpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
        this.__intercepted_url__ = url;
        _log(url, 'xhr');
        return _origXHROpen.apply(this, arguments);
    };

    function _hookHls(HlsClass) {
        if (!HlsClass || !HlsClass.prototype) return;
        if (HlsClass.prototype.__hls_hooked__) return;
        HlsClass.prototype.__hls_hooked__ = true;

        var _origLoad = HlsClass.prototype.loadSource;
        if (_origLoad) {
            HlsClass.prototype.loadSource = function (src) {
                _log(src, 'hlsjs_loadSource');
                return _origLoad.apply(this, arguments);
            };
        }

        var _origAttach = HlsClass.prototype.attachMedia;
        if (_origAttach) {
            HlsClass.prototype.attachMedia = function (media) {
                if (media && media.src) _log(media.src, 'hlsjs_attachMedia_src');
                return _origAttach.apply(this, arguments);
            };
        }
    }

    if (window.Hls) _hookHls(window.Hls);

    var _hlsWatchInterval = setInterval(function () {
        if (window.Hls) { _hookHls(window.Hls); clearInterval(_hlsWatchInterval); }
    }, 200);
    setTimeout(function () { clearInterval(_hlsWatchInterval); }, 15000);

    if (window.MediaSource && window.MediaSource.prototype) {
        var _origAddSB = window.MediaSource.prototype.addSourceBuffer;
        window.MediaSource.prototype.addSourceBuffer = function (mimeType) {
            _log('[MediaSource] addSourceBuffer: ' + mimeType, 'mediasource', { mimeType: mimeType });
            return _origAddSB.apply(this, arguments);
        };
    }

    var _origCreateObjURL = URL.createObjectURL;
    URL.createObjectURL = function (obj) {
        var blobUrl = _origCreateObjURL.apply(this, arguments);
        if (obj instanceof MediaSource) {
            _log(blobUrl, 'mediasource_blob');
        } else if (obj instanceof Blob) {
            _log(blobUrl, 'blob');
        }
        return blobUrl;
    };

    function _domSniff() {
        var videos = document.querySelectorAll('video[src]');
        for (var i = 0; i < videos.length; i++) {
            _log(videos[i].src, 'dom_video_src');
        }
        var sources = document.querySelectorAll('source[src]');
        for (var i = 0; i < sources.length; i++) {
            _log(sources[i].src, 'dom_source_src');
        }
        var dataAttrs = ['data-src', 'data-video', 'data-url', 'data-stream'];
        dataAttrs.forEach(function (attr) {
            var els = document.querySelectorAll('[' + attr + ']');
            for (var i = 0; i < els.length; i++) {
                _log(els[i].getAttribute(attr), 'dom_' + attr);
            }
        });
    }

    _domSniff();
    var _domInterval = setInterval(_domSniff, 500);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            _domSniff();
            clearInterval(_domInterval);
        });
    }
    setTimeout(function () { clearInterval(_domInterval); }, 15000);

    function _perfScan() {
        try {
            var entries = performance.getEntries();
            for (var i = 0; i < entries.length; i++) {
                var url = entries[i].name;
                _log(url, 'perf_entry');
            }
        } catch (e) {}
    }

    _perfScan();
    setTimeout(_perfScan, 2000);
    setTimeout(_perfScan, 5000);

    function _hookDash(DashClass) {
        if (!DashClass || DashClass.__dash_hooked__) return;
        DashClass.__dash_hooked__ = true;
        var _origCreate = DashClass.MediaPlayer || (DashClass.create && DashClass);
        if (DashClass.MediaPlayer && DashClass.MediaPlayer().initialize) {
            var _origInit = DashClass.MediaPlayer().initialize;
        }
        if (DashClass.prototype && DashClass.prototype.attachSource) {
            var _origAttachSrc = DashClass.prototype.attachSource;
            DashClass.prototype.attachSource = function(url) {
                _log(typeof url === 'string' ? url : (url && url.url) || '', 'dashjs_attachSource');
                return _origAttachSrc.apply(this, arguments);
            };
        }
    }

    if (window.dashjs)       _hookDash(window.dashjs);
    if (window.MediaPlayer)  _hookDash(window.MediaPlayer);

    var _dashWatchInterval = setInterval(function () {
        if (window.dashjs)      { _hookDash(window.dashjs);      }
        if (window.MediaPlayer) { _hookDash(window.MediaPlayer); }
    }, 300);
    setTimeout(function () { clearInterval(_dashWatchInterval); }, 15000);

})();
