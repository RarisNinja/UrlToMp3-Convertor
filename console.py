import argparse
from converter import UrlToMp3Converter

def show_results(result):

    results = result if isinstance(result, list) else [result]

    print("\n========== DONE ==========\n")

    for r in results:
        print(f"Title : {r['title']}")
        print(f"Folder: {r['folder']}")
        print(f"MP3   : {r['mp3']}")
        print(f"Cover : {r['cover'] or 'No cover'}")
        print("--------------------------")

    print("\n==========================\n")

def main():
    parser = argparse.ArgumentParser()
    
    parser.add_argument("url")

    args = parser.parse_args()

    converter = UrlToMp3Converter()

    result = converter.convert(args.url)

    show_results(result)


if __name__ == "__main__":
    main()