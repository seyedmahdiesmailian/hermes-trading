# Makefile for building Windows executable

.PHONY: install build clean run help

# Default target
all: build

# Install dependencies
install:
	@echo Installing dependencies...
	pip install -r requirements.txt
	pip install pyinstaller

# Build the executable
build:
	@echo Building Windows executable...
	pyinstaller forwarder.spec
	@echo.
	@echo Build complete! Executable is in dist\forwarder-telegram.exe
	@echo.
	@echo Remember to copy these files to the same folder as the .exe:
	@echo   - config.json
	@echo   - .env (if needed)
	@echo   - forwarder_session.session (after first run)

# Build using one-file mode (alternative)
build-onefile:
	@echo Building single-file executable...
	pyinstaller --onefile --name forwarder-telegram --console main.py
	@echo Build complete! Executable is in dist\forwarder-telegram.exe

# Clean build artifacts
clean:
	@echo Cleaning build artifacts...
	@if exist build rmdir /s /q build
	@if exist dist rmdir /s /q dist
	@if exist __pycache__ rmdir /s /q __pycache__
	@if exist forwarder-telegram.spec del forwarder-telegram.spec
	@echo Clean complete!

# Run the application (for testing)
run:
	@echo Running application...
	python main.py

# Test the built executable
test-exe:
	@echo Testing executable...
	@if exist dist\forwarder-telegram.exe (dist\forwarder-telegram.exe) else (echo ERROR: Executable not found! Run 'make build' first.)

# Help
help:
	@echo Available targets:
	@echo   make install       - Install required dependencies
	@echo   make build         - Build the executable using .spec file
	@echo   make build-onefile - Build single-file executable (alternative)
	@echo   make clean         - Clean build artifacts
	@echo   make run           - Run the Python script directly
	@echo   make test-exe      - Test the built executable
	@echo   make help          - Show this help message
