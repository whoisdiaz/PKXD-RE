# Animação e captura de mensagens na entrada — PK XD 1.38.4

O teste Android da revisão `31f1937` confirmou cache de slots, tabela de evolução
de pets, listas de veículos próprios/no mundo e um pacote de posição do avatar.
Após 12 segundos, o cliente fechou o TCP. O log não contém rejeição de pacote
ou timeout do servidor nessa tentativa. Isso não identifica uma exceção do APK.

## Variável de animação

`ToxicBirdAnimationMechanic` declara `USER_VARIABLE_MOTION_ANIMATION_STATE_KEY`
como `aaa`. `UpdateLocalPlayerAnimationVariables` (`0x30B6C44`) transforma os
dados do jogador em `PlayerAnimationData`, serializa em Protobuf, envolve em
ByteListVariable e chama SetVariableIfChanged. Não é uma escrita de inventário
ou compra. O pedido observado tem tipo 5 e 93 bytes de valor tipado; seu corpo
não foi registrado pelo servidor.

O servidor agora valida e confirma `aaa` como estado transitório da conexão,
sem alterar o banco de aparência. A resposta `tbulv` contém o ID autenticado
de transporte. Ao sair da sala, a animação é descartada. Apenas a primeira
atualização gera `TCP avatar animation state accepted`; o contador aparece
no resumo de encerramento da sessão.

`PlayerAnimationData` contém cinco mensagens AnimationData nos campos 1–5:
movimento, jogador com holdable, item holdable, jogador em veículo e veículo.
Há ainda HoldableToggledOn (bool 6) e ReactionIndex (int32 7). AnimationData
contém CurrentStateHash (int32 1), NextStateHash (int32 2), Progress (float 3)
e TransitionDuration (float 4). Os floats Protobuf são little-endian, diferentes
dos floats do evento binário de posição `C`.

`CommonTransformations.ToPlayerAnimationData` (`0x2DE43D8`) preenche as cinco
mensagens. O leitor `ToXDPlayerAnimationData` (`0x2DE42DC`) chama
`ToXDAnimationState` (`0x2DE4258`) para cada uma, que exige objeto não nulo.
Por isso o validador exige os cinco objetos presentes, mesmo que estejam vazios,
valida os wire types e floats finitos, e limita o Protobuf a 4096 bytes. Todas
as ocorrências de mensagens duplicadas são verificadas, pois o Protobuf C#
mescla essas ocorrências. A fixture de teste de 93 bytes é sintética, criada
do schema; não é uma captura do aparelho.

A recusa anterior de `aaa` apenas registrava o pedido e continuava a leitura.
Não foi demonstrado que ela causava o retorno ao login. O suporte corrige uma
lacuna real de animação, mas não substitui o diagnóstico da falha visual.

## Dependência do modelo de casa

`WaitForLocalPlayerInitStep.IsServiceReady` (`0x2EC0DE8`) verifica um
PlayerController existente, sua identificação e o ponteiro `_homeModel`
(`PlayerController +0x270`) não nulo. `PlayerCreateInitStep.CreateLocalPlayer`
(`0x3DCFFC4`) chama `CreateLocalHomeModel` (`0x3DD1138`) e registra erros como
`[PlayerCreation] Error Creating Local Player: ...`. O modelo é montado usando
IHouseMechanic e HomeModel. Essa dependência foi confirmada no código nativo;
não confirma que a exceção no aparelho ocorreu nesse modelo. Não foi escolhido
um ID de casa aleatório nem alterado o cliente para ignorar essa etapa.

`GameInitializationMonitorAsync.MoveNext` (`0x2165B50`) contém o log
`[GameController] Game initialization failed: ...` e o retorno à cena de login.
Precisamos desse erro, ou do erro anterior de PlayerCreation/Addressables, para
distinguir uma referência ausente, conteúdo não carregado ou etapa pendente.

Atualização: a captura ampliada recebeu os logs nativos, mas não os C#.
Foi confirmado que ApplicationManager.Awake desativa UnityLogger nessa build.
Veja o [patch de diagnóstico e teste dos links do bucket](client_logging_1_38_4.md)
para habilitar as mensagens de inicialização que o logcat sozinho não reativa.

## Capturar pelo próprio Termux

O Android precisa ter **Depuração sem fio**, ativada nas Opções do desenvolvedor.
No Termux:

```sh
pkg install android-tools
read -r -p "Porta da janela de pareamento: " pkxd_pair_port
adb pair "127.0.0.1:$pkxd_pair_port"
```

Mantenha Configurações e Termux em tela dividida. Abra **Parear dispositivo
com código** e digite somente a porta (os números após `:`) no primeiro prompt.
Digite o código quando o adb pedir. Após parear, volte à tela principal de
Depuração sem fio:

```sh
read -r -p "Porta da tela principal de Depuração sem fio: " pkxd_connect_port
adb connect "127.0.0.1:$pkxd_connect_port"
adb devices
```

As duas portas normalmente são diferentes. O endereço `127.0.0.1` refere-se
ao próprio celular. `adb devices` deve mostrar uma conexão autorizada com
estado `device`. Se o adb já estiver conectado, vá diretamente à captura.

Atualize o repositório e reinicie `python server.py` em uma sessão do Termux.
Abra o PK XD e deixe-o no menu. Em uma segunda sessão, execute:

```sh
cd ~/PKXD-RE
python tools/capture_android_startup.py
```

Volte ao jogo e toque em **Jogar** durante os 60 segundos da captura. Aguarde
até o comando terminar, inclusive se o jogo voltar ao menu. Ao terminar,
o script imprime o relatório e o salva em `data/android-startup.txt`, ignorado
pelo Git. Ctrl+C salva uma captura parcial e sua duração fica no relatório.
`--seconds 90` amplia a janela;
`--serial IP:PORTA` seleciona uma conexão quando há mais de uma em `adb devices`.

O script consulta o PID de `com.movile.playkids.pkxd` e captura as mensagens
desse processo em todos os níveis. Inclui até 500 linhas recentes de histórico,
pois a falha pode ter ocorrido antes de iniciar o comando. O relatório informa
horário inicial, duração, motivo do encerramento, número de linhas e se o PID
continuava ativo ao final. Um PID diferente é reportado, mas o leitor não passa
a seguir automaticamente esse novo processo.

São preservados o início/final até 64 KiB e até 16 KiB de trechos relacionados
a inicialização/erro com contexto, inclusive quando estão no meio de um log
grande. As linhas são sanitizadas antes do corte; parâmetros de URLs e
tokens/UUIDs em formatos conhecidos são ocultados. A captura continua
restrita ao PID do aplicativo. Mantenha o PK XD aberto antes de iniciar o
comando, para que seu PID exista. A opção `--errors-only` restaura o filtro
anterior Unity:E/AndroidRuntime:E, que pode omitir avisos e mensagens de espera.

Essa ampliação foi feita depois de uma tentativa na revisão `a06a94c`:
o servidor aceitou `aaa`, recebeu posição e respondeu aos veículos, mas o jogo
voltou ao menu e a captura anterior terminou por Ctrl+C sem erros registrados.
Esse resultado não permite concluir que o APK não tenha falhado nem que a
interrupção tenha ocorrido antes da falha. Se o leitor ADB perder a conexão,
o relatório agora preserva as mensagens recebidas e informa o status do leitor.

Compartilhe o texto do relatório, sobretudo as linhas de **PlayerCreation**,
**Game initialization failed**, **Exception** ou **Addressables** e suas pilhas.
Se não houver mensagens, envie também o cabeçalho com a contagem de linhas e
o estado do PID/ADB. Isso distingue uma coleta vazia de uma coleta em que os
logs foram recebidos, mas não houve uma exceção registrada.
