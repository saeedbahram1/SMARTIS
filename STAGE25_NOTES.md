Stage 25 hotfix
- Fixed command engine self-test: natural multi-action sentences now split on clear Persian/English conjunctions and reuse fast-path semantics.
- Restored robust online direct VLC playback based on the Stage 22 extractor path, including yt-dlp JS-runtime detection and VLC HTTP headers.
- Added SETUP_MEDIA_PLAYBACK.bat for online VLC mode. It does not install YouTube/Selenium browser automation or local-folder music mode.
- No local Music/Downloads/Desktop media search is used by play_media_search.
