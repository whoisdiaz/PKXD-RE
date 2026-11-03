# Animação e captura de erro na entrada — PK XD 1.38.4

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

## Capturar pelo próprio Termux

O Android precisa ter **Depuração sem fio**, ativada nas Opções do desenvolvedor.
No Termux:

```sh
pkg install android-tools
adb pair IP:PORTA_DE_PAREAMENTO
adb connect IP:PORTA_DE_CONEXAO
adb devices
```

Use o IP/porta mostrados em **Parear dispositivo com código** no comando
`adb pair` e digite o código no prompt do adb. Use o IP/porta da tela principal
de Depuração sem fio no `adb connect`. As duas portas normalmente são diferentes.
O comando `adb devices` deve mostrar uma conexão autorizada com estado `device`.

Atualize o repositório e reinicie `python server.py` em uma sessão do Termux.
Abra o PK XD e deixe-o no menu. Em uma segunda sessão, execute:

```sh
cd ~/PKXD-RE
python tools/capture_android_startup.py
```

Volte ao jogo e toque em **Jogar** durante os 45 segundos da captura. Ao terminar,
o script imprime o relatório e o salva em `data/android-startup.txt`, ignorado
pelo Git. Ctrl+C encerra e salva o que já chegou. `--seconds 90` amplia a janela;
`--serial IP:PORTA` seleciona uma conexão quando há mais de uma em `adb devices`.

O script consulta o PID de `com.movile.playkids.pkxd` e pede apenas erros das
tags Unity e AndroidRuntime desse processo. Preserva o início/final até 64 KiB,
remove parâmetros de URLs e oculta tokens/UUIDs em formatos conhecidos. Não
coleta logs de outros processos nem altera o APK. Mantenha o aplicativo aberto
antes de iniciar a captura, para que seu PID exista.

Compartilhe o texto do relatório, sobretudo as linhas de **PlayerCreation**,
**Game initialization failed**, **Exception** ou **Addressables** e suas pilhas.
Se o relatório disser que nenhum erro foi capturado, esse também é um resultado
útil: o próximo diagnóstico precisará de outra fonte de evidência.
