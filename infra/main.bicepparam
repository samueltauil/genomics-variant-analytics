using './main.bicep'

// Environment-specific values stay out of source control; supply them through the environment.
param environmentName = readEnvVar('GENOMICS_ENV_NAME', 'demo')
param location = readEnvVar('GENOMICS_LOCATION', 'eastus2')
param deployerPrincipalId = readEnvVar('GENOMICS_DEPLOYER_OBJECT_ID')
param expiresOn = readEnvVar('GENOMICS_EXPIRES_ON')
param landingShareQuotaGiB = int(readEnvVar('GENOMICS_SHARE_QUOTA_GIB', '128'))
param landingProvisionedIops = int(readEnvVar('GENOMICS_SHARE_IOPS', '3000'))
param landingProvisionedBandwidthMibps = int(readEnvVar('GENOMICS_SHARE_MIBPS', '200'))
