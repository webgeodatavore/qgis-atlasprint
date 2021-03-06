## AtlasPrint: QGIS Server Plugin to export PDF from composer with atlas capabilities

### Description

This plugin adds a new request to QGIS 3 Server `getprintatlas` which allows to export a print composer with an atlas configured, but passing an expression parameter to choose which feature is the current atlas feature.

### Installation

We assume you have a fully functional QGIS Server with Xvfb. See [the QGIS3 documentation](https://docs.qgis.org/3.4/en/docs/user_manual/working_with_ogc/server/index.html).

We need to download the plugin, and tell QGIS Server where the plugins are stored, then reload the web server.
For example on Debian:

```bash
# Create needed directory to store plugins
mkdir -p /srv/qgis/plugins

# Get last version
cd /srv/qgis/plugins
wget "https://github.com/3liz/qgis-atlasprint/archive/master.zip"
unzip master.zip
mv qgis-atlasprint-master atlasprint

# Make sure correct environment variables are set in your web server configuration
# for example in Apache2 with mod_fcgid
nano /etc/apache2/mods-available/fcgid.conf
FcgidInitialEnv QGIS_PLUGINPATH "/srv/qgis/plugins/"

# Reload server, for example with Apache2
service apache2 reload
```

You can now test your installation.

### API

This plugin adds some new requests to the WMS service:
* `REQUEST=GetCapabilitiesAtlas`: Return the plugin version
* `REQUEST=GetPrintAtlas`
  * `TEMPLATE`: **required**, name of the layout to use.
  * `EXP_FILTER`: **required**, (in some case must be urlencoded). For example, to request `fid=12`, use `&EXP_FILTER=fid%3D12`.
  * `MAP`: QGIS Server can have the project information from different sources.
* `REQUEST=GetReport`
  * `TEMPLATE`: **required**, name of the report to use.
  * `MAP`: QGIS Server can have the project information from different sources.

> Note: For QGIS a report is the same as an atlas. 
> Atlases and reports share the name space, so doing
> `REQUEST=GetPrintAtlas&TEMPLATE=demo&EXP_FILTER=""` is equivalent to 
> `REQUEST=GetReport&TEMPLATE=demo`
