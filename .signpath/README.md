# SignPath code signing

The release workflow signs Windows EXE and Android APK artifacts using SignPath. MacOS artifact signing is pending registration with Apple Developer ID.

Both platforms use [SignPath GitHub Actions](https://docs.signpath.io/trusted-build-systems/github) cloud signing (`authenticode-sign` for the portable EXE, `apk-sign` for the APK).

Thank you [SignPath.io](https://signpath.io) for the OSS sponsorships.
