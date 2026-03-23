# BirdNET-Go Classifiers

Custom TensorFlow Lite format AI model classifiers for enhanced bird and wildlife identification, designed for use with [BirdNET-Go](https://github.com/tphakala/birdnet-go) and BirdNET Analyzer.

## Overview

This repository contains specialized BirdNET classifier models that extend the capabilities of the base BirdNET v2.4 model. These classifiers focus on improving detection accuracy for specific species and adding support for new species not included in the original model. This repo is aimed at getting better results for Nagpur, Maharashtra, India.

## Current Model Version

**BirdNET-Go_classifier_20250916**

- Base Model: BirdNET v2.4
- Format: TensorFlow Lite (.tflite)
- Release Date: September 16, 2025

## Supported Species

### Augmented Classes
These species have enhanced detection capabilities compared to the base BirdNET model:

- **Passer domesticus** - House Sparrow


## Installation & Usage

### With BirdNET-Go
1. Download the latest classifier model from the releases section
2. Place the `.tflite` file in your BirdNET-Go models directory (birdnet-go-app/data/models/)
3. Place the `*_Labels.txt` next to `.tflite` file in models directory
4. Configure BirdNET-Go to use the custom classifier in config.yaml
     - Set modelpath to "models/BirdNET-Go_classifier_20250916.tflite"
     - Set labelpath to "models/BirdNET-Go_classifier_20250916_Labels.txt"
     - Restart BirdNET-Go
5. Refer to the [BirdNET-Go documentation](https://github.com/tphakala/birdnet-go) for detailed setup instructions

## Utility scripts

The `utils/` folder has optional Python helpers for training data: `slice_my_recordings.py` (slice audio into clips) and `xeno_canto_download.py` (download from Xeno-Canto). You do not need them to install or run the classifier models from releases but they are helpful for gathering data.

## Changelog

### 20260323
- More data and better negatives
- 1 species
    - **Passer domesticus** - House Sparrow

### 20260321
- Starting with 1 species
- Added 1 new augmented species:
    - **Passer domesticus** - House Sparrow

- Optimized for BirdNET-Go and BirdNET Analyzer compatibility

## License

This project follows the same licensing terms as the base BirdNET model. Please refer to the BirdNET project for license details.

## Acknowledgments

- Built upon the excellent work of the [BirdNET](https://github.com/birdnet-team/BirdNET-Analyzer) project
- Designed for seamless integration with [BirdNET-Go](https://github.com/tphakala/birdnet-go)
- Community contributions and feedback
  - *Ovis aries* audio samples provided by Martin HinzundKunz @HinzundKunz

## Support

For issues and questions:
- BirdNET-Go specific: [BirdNET-Go Issues](https://github.com/tphakala/birdnet-go/issues)
- Model-specific issues: Use this repository's issue tracker
- General BirdNET questions: Refer to the main BirdNET project