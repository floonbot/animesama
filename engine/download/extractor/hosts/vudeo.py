from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="vudeo",
    domains=("vudeo.io", "vudeo.net", "vudeo.co"),
    prefer_ytdlp=False,
    referer="https://vudeo.io/",
    note="MP4/HLS via lecteur JS ; capture par interception reseau + Referer vudeo",
))
