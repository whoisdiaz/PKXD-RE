# Logs C# desativados no cliente e teste de pkxd-bucket

## O que a captura confirmou

A captura enviada recebeu 554 linhas, 41 mencionando Unity. Terminou por Ctrl+C
após 25,6 segundos e o PID continuava ativo. Há avisos nativos de minimapa,
SpriteAtlas e LODGroup, além de mensagens dos SDKs Android/anúncios. Não há a
exceção de PlayerCreation/GameController que identifica o retorno ao menu.
Esses avisos, sozinhos, não provam a causa da falha.

Foi localizada uma causa concreta da ausência de logs C#: no binário ARM64
fornecido, `PlayKids.XD.ApplicationManager.Awake` (RVA `0x2738D18`) obtém
Debug.unityLogger e chama `ILogger.set_logEnabled(false)`. A interface ILogger
define esse setter no slot 2, usado pela chamada em `0x2738E90`.
O argumento é definido por `mov w1, wzr` em `0x2738E8C`.
Por isso os avisos do motor nativo podem aparecer enquanto os logs C# ficam
silenciados. Mudar apenas o filtro do logcat não reativa esse logger.

## Patch de diagnóstico

| Propriedade | Valor |
| --- | --- |
| Build | libil2cpp.so ELF64 AArch64, 91.868.752 bytes |
| SHA-256 original | `32e8e598619d9ff1136a184b39b0c93b19a461b56ef612bb56871072765e6fbe` |
| Offset de arquivo / RVA | `0x2738E8C` |
| Quatro bytes originais | `e1 03 1f 2a` — mov w1, wzr |
| Quatro bytes de diagnóstico | `21 00 80 52` — mov w1, #1 |
| SHA-256 com logs | `39251a034d833e74e48797eed3b608732d7a952f9dafdc55b1a5ef48e964856e` |

O patch troca somente o argumento false por true antes da chamada já existente.
Foi aplicado à lib original em uma cópia, e os quatro offsets modificados e o
SHA de saída foram verificados. Isso habilita diagnóstico, não corrige por si
só a entrada no mundo. A validação no APK após instalar essa cópia está pendente.

`tools/enable_client_logging.py` verifica tamanho, ELF/ABI, SHA e instrução antes
de gerar uma cópia. Uma lib de outra build é recusada. Aceita a lib original ou
a variante de diagnóstico conhecida e oferece `--restore` para gerar os quatro
bytes originais em outra pasta. Não sobrescreve a lib de entrada nem uma lib de
saída desconhecida.

## Gerar pelo Termux e substituir com MT Manager

Com o adb já conectado ao mesmo celular:

```sh
cd ~/PKXD-RE
git pull --ff-only
termux-setup-storage
python tools/enable_client_logging.py --from-device --output-dir ~/storage/downloads/PKXD-logging
```

O script consulta `pm path` para o PK XD, lê o APK instalado e procura a lib
ARM64. Quando houver split de ABI, ele é examinado primeiro. O APK temporário
é removido depois da leitura. A lib gerada e seu manifesto ficam em
**Download/PKXD-logging**. O aplicativo instalado não é assinado, instalado ou
desinstalado pelo script.

Se o SHA não corresponder, envie a mensagem da ferramenta: ela identifica uma
diferença entre a lib instalada e a build estudada, sem aplicar offsets às cegas.
Também é possível fornecer um APK local por `--apk caminho.apk`, ou a biblioteca
extraída pelo MT Manager por `--library caminho/libil2cpp.so`.

No MT Manager, trabalhe em uma cópia do APK já modificado para contas/lobby.
Substitua **lib/arm64-v8a/libil2cpp.so** pela lib gerada em Download/PKXD-logging.
Assine com a mesma chave/configuração usada na instalação atual e instale como
atualização, preservando os dados. O global-metadata.dat já redirecionado continua
nesse APK. A biblioteca pode estar no split de ABI em pacotes divididos; nesse
caso, o arquivo indicado no manifesto é o APK que contém a lib.

Abra novamente o jogo no menu. Com o servidor rodando em outra sessão:

```sh
python tools/capture_android_startup.py --seconds 60
```

Toque em Jogar durante a captura e aguarde o término automático. A expectativa
é passar a receber também logs C# como `[PlayerCreation]`, `[InitStep]` e
`[GameController]`, além do erro específico da inicialização, se houver.

## Hipótese dos links pkxd-bucket

Os literais do metadata enviado contêm estes seis JSONs públicos:

- `creators/creators-panels.json`
- `news/news.json`
- `recurrent-activity/recurrent_activities_config.json`
- `server-health/health.json`
- `soft-update/update-info.json`
- `ugc-teleporter-config/ugc-teleporter-config.json`

Todos usam `https://pkxd-bucket.aftvrsys.com/`. Há também o diretório `news/`,
que não é um objeto JSON de configuração. O catalog.json enviado contém 97 IDs
de bundles e nenhuma URL HTTP literal; isso não exclui outros catálogos ou
transformações de endereço em tempo de execução.

O retriever de saúde (`0x39FF624`) e o de portais (`0x3294F04`) validam HEAD
antes do download. Suas falhas chamam Debug.LogError, que também era silenciado
pelo logger desativado. Logo, o diagnóstico precisa conferir HEAD e GET, não
apenas se o navegador abre o domínio. Acessibilidade não foi verificada por
HTTP na nuvem; a política desse ambiente não concede acesso a esse host.

Para testar os objetos na mesma rede do jogo, sem instalar pacotes Python:

```sh
cd ~/PKXD-RE
python tools/check_pkxd_bucket.py
```

O relatório em `data/pkxd-bucket.json` registra status HTTP de HEAD/GET,
Content-Type, Content-MD5/ETag, validade do JSON e distingue erro de DNS, TLS ou
timeout. Os valores do JSON baixado não são gravados. O User-Agent do teste é
`PKXD-RE/bucket-diagnostic`, informado no relatório; ele não reproduz todos os
headers ou o cache do UnityWebRequest. Status e JSON devem ser confrontados
com o erro real do APK antes de mudar seus endereços.

Uma URL antiga falhar não demonstra sozinha que causou o retorno ao menu. A
implementação futura de uma configuração local precisa manter o schema que o
cliente espera; substituir todas as URLs por localhost sem esse conteúdo não
resolve essa dependência. Os testes e a validação estão em
[client-logging-verification.json](client-logging-verification.json).
