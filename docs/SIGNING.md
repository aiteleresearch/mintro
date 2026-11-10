# Signing the installer

People download `MINTRO-Setup-x.y.z.exe` from the website. Windows marks the download as coming from the
internet, and when it's opened, Microsoft Defender SmartScreen (and on newer Windows 11 PCs, Smart App Control)
decides what happens:

| The file is | What people see |
|---|---|
| Unsigned | "Windows protected your PC", publisher "Unknown". They have to click *More info > Run anyway*, and many won't. Smart App Control blocks unsigned apps outright, with no way past. |
| Signed with a trusted certificate, new | The publisher's name instead of "Unknown". SmartScreen may still show its warning until the certificate has reputation, but Smart App Control lets a validly signed app run. |
| Signed, with reputation | Nothing: it opens like any other app. |

Reputation is earned per certificate as people download and run your signed files without trouble. No
certificate skips that step any more (EV certificates used to; Microsoft ended it in 2024), so an expensive EV
certificate isn't worth it for this. What matters is to sign every release, always with the same certificate.

There is no shortcut: a trusted certificate is issued only after a certificate authority checks who you are, so
it has to be bought by you (or aitele research). A self-signed certificate is trusted by nobody's PC and does
not help.

## What the build already does

- **Signs both exes** (`MINTRO.exe` and the setup file) when a certificate is configured, with SHA-256 and an
  RFC 3161 timestamp, so the signature stays valid after the certificate expires. The build ends with a
  SIGNED/UNSIGNED line for each.
- **Version information** in both exes: publisher "aitele research", product MINTRO, version, copyright.
  Windows shows it in *Properties > Details*, and antivirus heuristics trust files that have it.
- **Installs per user, without admin rights**, so there is no UAC prompt.
- **Nothing installed carries the download mark**: only the setup file is checked by SmartScreen. Once
  installed, MINTRO opens without warnings, and updates install without any.
- Updates are also checked against MINTRO's own publisher key (`docs/UPDATES.md`). That is separate from code
  signing and stays in place either way.

## Choose a certificate

**1. Azure Artifact Signing** (formerly Trusted Signing): about $10 a month, no hardware, and certificates
Microsoft manages, which suit SmartScreen well. Microsoft limits who can sign up (when last checked:
organisations in the US, Canada, the EU and the UK, and individual developers in the US and Canada), so check
the current eligibility first. If aitele research qualifies, use this.

**2. Certum Open Source Code Signing** (the "in the Cloud" variant, with the SimplySign app): the cheapest
option open to individual developers anywhere, including India. MINTRO is GPL-3.0 with public source, so it
qualifies. The certificate names a person ("Open Source Developer, Shashank Taxak"), not the company. The
private key stays in Certum's cloud. SimplySign Desktop makes the certificate appear in the Windows certificate
store while you're signed in, and signtool uses it from there.

**3. An OV certificate for the company** (Sectigo, SSL.com, DigiCert, GlobalSign and their resellers): shows
"aitele research" as the publisher, but needs a registered business that the authority can verify (a public
company registry or D-U-N-S number). It costs more each year, and the key lives on a USB token or in the
issuer's cloud signing service.

If aitele research is registered and can't use Azure, choose option 3 so the company name shows. Otherwise
choose option 2.

## Sign a release

### With a certificate in the Windows store (Certum SimplySign, a USB token, most OV certificates)

1. Sign in to SimplySign Desktop, or plug in the token.
2. Find the certificate's thumbprint:
   ```powershell
   Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Format-List Subject, Thumbprint, NotAfter
   ```
3. Build:
   ```powershell
   $env:MINTRO_SIGN_THUMBPRINT = "<thumbprint>"
   py -3.12 setup\build.py
   ```
   For Certum, you can also set `$env:MINTRO_SIGN_TIMESTAMP = "http://time.certum.pl"`. The default (DigiCert's
   timestamp server) works with any certificate.

### With Azure Artifact Signing

1. In the Azure portal: create an Artifact Signing account, complete identity validation, create a
   **Public Trust** certificate profile, and give your user the *Certificate Profile Signer* role on it.
2. Install Microsoft's signing client tools (the "dlib"; Microsoft's guide *Set up signing integrations*
   has the current download) and the Azure CLI, then `az login`.
3. Save a `metadata.json` outside the repository:
   ```json
   {
     "Endpoint": "https://<region>.codesigning.azure.net/",
     "CodeSigningAccountName": "<account name>",
     "CertificateProfileName": "<profile name>"
   }
   ```
4. Build:
   ```powershell
   $env:MINTRO_SIGN_DLIB = "<path>\Azure.CodeSigning.Dlib.dll"
   $env:MINTRO_SIGN_METADATA = "<path>\metadata.json"
   py -3.12 setup\build.py
   ```
   The timestamp server defaults to Microsoft's (`http://timestamp.acs.microsoft.com`).

### With a .pfx file

`MINTRO_SIGN_PFX` and `MINTRO_SIGN_PASSWORD`. Certificate authorities no longer issue code-signing keys as
files, so this is only for older certificates.

### Check the result

```powershell
Get-AuthenticodeSignature dist\MINTRO-Setup-x.y.z.exe | Format-List Status, SignerCertificate, TimeStamperCertificate
```

`Status` must be `Valid`. *Properties > Digital Signatures* on the file shows the same.

## After each release

1. Upload the signed setup file and the update package (`docs/UPDATES.md`).
2. Submit the setup file to Microsoft (*Software developer*,
   https://www.microsoft.com/en-us/wdsi/filesubmission). It clears false detections and helps SmartScreen
   reputation along. `docs/ANTIVIRUS.md` has the text to paste and the other vendors.
3. Keep the same certificate when you renew. A new certificate from another issuer starts its reputation
   again from zero.

## Until it's signed

The website prepares people for the warnings instead of hoping they push through. Every Download button starts
the download and opens a short guide (`docs/assets/download.js`):
1. if the browser says the file isn't commonly downloaded, choose *Keep*;
2. Windows shows "Windows protected your PC": *More info*, then *Run anyway* (with an animated picture of that
   screen and the exact file name, read from `download/release.json`);
3. MINTRO Setup opens: *Install*.

It also says why the warning appears, and that PCs with Smart App Control on can't install unsigned apps at
all. On a phone or a Mac, Download explains that MINTRO is for Windows and offers to send the link to a PC
instead of downloading an .exe. The FAQ and the download section open the same guide. Once the release is
signed and SmartScreen stops warning, change the guide's wording in `download.js` (or remove the script and the
`data-dl-guide` links).
