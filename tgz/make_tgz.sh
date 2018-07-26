#!/bin/bash
if [ `dirname $0` != "." ]; then
        echo "You should run this script from `dirname $0`"
        exit;
fi
rm -rf sysadmws-utils-v1
cp -R ../deb/sysadmws-utils-v1 .
cat sysadmws-utils-v1/DEBIAN/control | grep Version > sysadmws-utils-v1/opt/sysadmws/VERSION
rm -rf sysadmws-utils-v1/DEBIAN
sudo chown -R root:root sysadmws-utils-v1
sudo tar zcf sysadmws-utils-v1.tar.gz -C sysadmws-utils-v1 .
sudo rm -rf sysadmws-utils-v1
