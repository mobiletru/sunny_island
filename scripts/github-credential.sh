#!/bin/sh
TOKEN_FILE="/root/.github-token"

case "$1" in
  get)
    if [ ! -f "$TOKEN_FILE" ]; then
      exit 1
    fi
    TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE")
    echo "username=x-access-token"
    echo "password=$TOKEN"
    ;;
  store|erase)
    ;;
  *)
    exit 1
    ;;
esac
