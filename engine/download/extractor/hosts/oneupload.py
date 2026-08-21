from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="oneupload",
    domains=("oneupload.to", "oneupload.net", "oneupload.cc", "oneupload.stream"),
    prefer_ytdlp=False,
    referer="https://oneupload.to/",
    note="XFileSharing ; yt-dlp ne le gere pas (Unsupported URL) -> extraction via sniff navigateur Playwright",
))
