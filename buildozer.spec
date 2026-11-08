
[app]

title = Elyx IDE
package.name = ELYX-IDE
package.domain = org.akilesh

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt,ttf,otf,html,css,js,md
source.exclude_dirs = .git,.github,.buildozer,bin,venv,.venv,__pycache__

version = 0.1.0

# App icon and splash screen (files in the elyx_android_brand_assets folder).
# The splash colour fills the screen around the splash image; set it to match
# the splash image's background if you see a visible edge.
icon.filename = %(source.dir)s/elyx_android_brand_assets/elyx_icon.png
presplash.filename = %(source.dir)s/elyx_android_brand_assets/elyx_splash.png
android.presplash_color = #282a36

# Core Kivy app dependencies.
# pyjnius and android are used for the storage permission screens.
# Pygame requires a compatible Android build recipe.
requirements = python3,kivy,pygments,pyjnius,android

orientation = portrait
fullscreen = 0

# Python-for-Android configuration
p4a.fork = kivy
p4a.branch = develop
p4a.bootstrap = sdl2

# Android SDK and NDK
android.api = 36
android.minapi = 24
android.ndk = 29
android.ndk_api = 24
android.archs = armeabi-v7a

# Application permissions
# Elyx works directly on files in shared storage (the Elyx folder).
# Android 11+ uses MANAGE_EXTERNAL_STORAGE ("All files access", switched on in
# Settings); Android 10 and older use the READ/WRITE_EXTERNAL_STORAGE pair.
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

# Build configuration
android.accept_sdk_license = True
android.allow_backup = True
android.debug_artifact = apk
android.release_artifact = apk

[buildozer]

log_level = 2
warn_on_root = 1
