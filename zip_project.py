import os
import zipfile

# Project directory and output path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
# Save the zip file in the Desktop
ZIP_FILE_PATH = os.path.expanduser("~/Desktop/ARIA_NEXUS_SourceCode.zip")

# Directories to exclude from the zip file
EXCLUDE_DIRS = {
    'venv',
    '.venv',
    'env',
    'vendor',
    'models',
    'chroma_db',
    '.git',
    '__pycache__',
    'node_modules'
}

# File extensions to exclude
EXCLUDE_EXTENSIONS = {
    '.zip',
    '.tar.gz',
    '.pyc',
    '.pyo',
    '.db',
}

def create_zip():
    print(f"Starting to zip project from: {PROJECT_DIR}")
    print(f"Excluding directories: {', '.join(EXCLUDE_DIRS)}")
    print(f"Output will be saved to: {ZIP_FILE_PATH}")
    
    count = 0
    with zipfile.ZipFile(ZIP_FILE_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_DIR):
            # Modify dirs in-place to prevent walking into excluded or hidden directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
            
            for file in files:
                # Skip hidden files like .gitignore or config files starting with a dot
                if file.startswith('.'):
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDE_EXTENSIONS:
                    continue
                
                file_path = os.path.join(root, file)
                # Keep directory structure inside the zip
                arcname = os.path.relpath(file_path, PROJECT_DIR)
                zipf.write(file_path, arcname)
                count += 1
                
    print(f"\nSuccessfully zipped {count} files!")
    print(f"Archive created at: {ZIP_FILE_PATH}")

if __name__ == "__main__":
    create_zip()
