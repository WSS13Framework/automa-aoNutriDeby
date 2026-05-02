#!/usr/bin/env python3
# Gera um CSV de teste com as primeiras 50 linhas do seu CSV real
# (copie as primeiras 50 linhas do seu CSV original aqui)
import os

# Substitua este conteúdo pelas PRIMEIRAS 50 LINHAS do seu CSV real
# (você pode copiar apenas as linhas 1 a 50 do arquivo original)
csv_teste = """sep=|
Nome|Email|Ativo|Data de nascimento|Sexo|Celular|Telefone|Data de cadastro|Ocupaçăo|CPF|CEP|Endereço|Número|Complemento|Bairro|Cidade|Estado|Observaçăo|Local de atendimento
moises santos oliveira|lillicaoliveirasantos03@gmail.com|Não| 29/08/1976|Masculino|=""|=""| 27/09/2018||=""|=""||||||||
Jorge Bento|jlbs976@hotmail.com|Não| 23/03/1982|Masculino|="999178117"|=""| 11/10/2018||=""|=""||||||||Escultura do Corpo
Jacqueline Reis|jacquelinereis1991@gmail.com|Não| 25/12/1991|Feminino|="972314050"|=""| 29/10/2018|microempresária |=""|=""||||||||
JENNIFER LIMA|jhenniferlima020@gmail.com|Não| 11/04/2001|Feminino|=""|=""| 11/11/2018||=""|=""||||||||
wilson oliveira|w.oliveiraadv@hotmail.com|Não| 06/06/1969|Masculino|=""|=""| 22/11/2018|advogado|=""|=""||||||||
evelyn abreu|evelynabreu88@yahoo.com.br|Não| 31/01/1988|Feminino|="21 998173470"|=""| 22/11/2018||=""|=""||||||||
Edileuza de Morais|penelopemorais1@gmail.com|Não| 03/05/1973|Feminino|=""|=""| 24/11/2018||=""|=""||||||||
Wagner Tavares Mariano|wagnertm1@gmail.com|Não| 19/04/1978|Feminino|="21983646707"|=""| 14/12/2018||=""|=""||||||||
PRISCILA SOUZA DO NASCIMENTO|rjpriscila.souza@gmail.com|Não| 07/02/1987|Feminino|="21990524602"|=""| 15/12/2018|tecnica de laboratorio|=""|=""||||||||
Edneia Soares da Silva Ferraz|edneiaferraz0@gmail.com|Não| 24/03/1972|Feminino|="21964933786"|=""| 18/12/2018|estudante|=""|=""||||||||Escultura do Corpo
Raquel Sena Da Silva|raqsds@hotmail.com|Não| 06/02/1987|Feminino|="994840644"|=""| 19/12/2018|atendente|=""|=""||||||||
Ana Paula Barbosa|paulinha91692@gmail.com|Não| 12/08/1988|Feminino|="21980612445"|=""| 21/12/2018|do lar|=""|=""||||||||Escultura do Corpo
Ismar luiz silva Caldas|iscal2013@yahoo.com.br|Não| 13/12/1981|Masculino|="21970148711"|=""| 26/12/2018||=""|=""||||||||
Sueli Maria dos Santos|suelimds35@icloud.com|Não| 09/06/1984|Feminino|="21974267996"|=""| 26/12/2018|pedagoga|=""|=""||||||||Escultura do Corpo
jullyana da cabral|jullyanacabral@gmail.com|Não| 05/04/1990|Masculino|="21971674783"|=""| 04/01/2019||=""|=""||||||||Escultura do Corpo
Wagner Luiz Guedes dos Santos |zileidejoaovictor@gmail.com|Não| 20/03/1988|Masculino|="+5521992881614"|=""| 07/01/2019||=""|=""||||||||Escultura do Corpo
camila vicente||Não| 30/04/1990|Feminino|="21979984217"|=""| 11/01/2019||=""|=""||||||||Escultura do Corpo
Elaine cristina da silva pinto||Não| 12/06/1976|Feminino|="21974242255"|=""| 15/01/2019||=""|=""||||||||
ROSEMERI DA CONCEIÇĂO MARTINS||Não| 18/04/1965|Feminino|="975765849"|=""| 18/01/2019||=""|=""||||||||
Glaucia da Cunha Medeiros|glauciadacunhamedeiros@yahoo.com.br|Não| 23/05/1988|Feminino|="99968-2451"|=""| 21/01/2019||=""|=""||||||||Escultura do Corpo
JESSICA SOUZA CARVALHO DE OLIVEIRA |js_souza_23@hotmail.com|Não| 24/04/1985|Feminino|="2196997-9931"|=""| 21/01/2019||=""|=""||||||||
solange rodrigues da silva dantas|solrodriguesdp@gmail.com|Não| 12/03/1964|Feminino|="21997455512"|=""| 24/01/2019||=""|=""||||||||
Luciano Dos Santos Misael |luck2000show@gmail.com|Não| 24/02/1962|Masculino|="21998361128"|=""| 24/01/2019||=""|=""||||||||
Matheus Bonfim Barbosa|matheusgrandejogador123@hotmail.com|Não| 27/05/1998|Masculino|="21 97349-2016"|=""| 01/02/2019||=""|=""||||||||
Edson Souza Ferreira|samba.conexaonews@gmail.com|Não| 07/04/1979|Masculino|=""|=""| 01/02/2019||=""|=""||||||||
Rodrigo Assis de Oliveira|rodrigoherculesrj@gmail.com|Não| 13/10/1978|Masculino|=""|=""| 06/02/2019||=""|=""||||||||
Livia de Brito Rodrigues|visualnatural@gmail.com|Não| 06/08/1983|Feminino|="21964237848"|=""| 07/02/2019||=""|=""||||||||
Danielle de Castro Queiroz da Cruz||Não| 25/09/1976|Feminino|="21980684087"|=""| 08/02/2019||=""|=""||||||||Escultura do Corpo
Diogo vinícius oliveirade lima|ldiogo968@gmail.com|Não| 04/02/2007|Feminino|=""|=""| 10/02/2019||=""|=""||||||||Escultura do Corpo
Carlos Henrique Nascimento Diorato|dircivil.vl@gmail.com|Não| 26/09/1974|Masculino|="986151810"|=""| 11/02/2019||=""|=""||||||||
Lavinia de brito Rodrigues|alexanderbarrao84@gmail.com|Não| 17/04/2010|Feminino|=""|=""| 11/02/2019||=""|=""||||||||
SIMONE GARCIA DIAS|EDUDIGITAL@GMAIL.COM|Não| 24/03/1974|Feminino|="964858330"|=""| 24/02/2019||=""|=""||||||||
TIAGO SANTOS S. DE ALMEIDA SOUZA||Não| 10/02/1990|Masculino|="969896907"|=""| 24/02/2019||=""|=""||||||||Escultura do Corpo
Rosemberg da Silva Medeiros Gomes||Não| 19/01/1975|Masculino|="21971091350"|=""| 27/02/2019||=""|=""||||||||
Fiamma Keli de Souza Guimarăes||Não| 18/01/1993|Feminino|="+5521997487249"|=""| 27/02/2019||=""|=""||||||||Escultura do Corpo
Elizanea Fonseca de Almeida |liz.almeida@hotmail.com|Não| 19/05/1975|Feminino|=""|=""| 01/03/2019||=""|=""||||||||
Francisco Rafael  Santos de Mendonça|kikorafa32@gmail.com|Não| 13/06/1982|Masculino|="984934706"|=""| 08/03/2019||=""|=""||||||||Escultura do Corpo
Alexandre Da Siva  Malhado|alexandredasilva81@gmail.com|Não| 31/12/1974|Masculino|=""|=""| 08/03/2019||=""|=""||||||||
Camila Figueira da Silva ||Năo| 10/07/1996|Masculino|=""|=""| 08/03/2019||=""|=""||||||||
Stephanie Alessandra de Luna Brandao||Năo| 08/11/1991|Feminino|="21 9743-9654"|=""| 14/03/2019||=""|=""||||||||
CRISTIANE DE MOURA VEIGA||Năo| 05/10/1980|Feminino|="21 990644760"|=""| 15/03/2019||=""|=""||||||||Escultura do Corpo
Daniela Vieira de andrade||Năo| 30/08/1995|Masculino|="97671-7936"|=""| 15/03/2019||=""|=""||||||||
Rosilene Maria da Silva Oliveira|rosyrcc10@gmail.com|Năo| 10/04/1992|Feminino|="2196962-6145"|=""| 19/03/2019||=""|=""||||||||
Camilla Pegoral Mageski||Năo| 25/07/1988|Feminino|="21998588364"|=""| 19/03/2019|professara|=""|=""||||||||
Tamiris Gos de Almeida |tamirisalmeida2007@gmail.com|Năo| 06/12/1989|Feminino|=""|=""| 31/03/2019||=""|=""||||||||
BRUNO DOS SANTO MUNIZ|BRUNOMUNIZROUPAS@GMAIL.COM|Năo| 20/05/1982|Masculino|="21964025177"|=""| 02/04/2019||=""|=""||||||||
Gadiele Ferreira Pinto||Năo| 25/12/1995|Feminino|="973498203"|=""| 10/04/2019||=""|=""||||||||Escultura do Corpo
Max Oliveira de Medeiros|Maxbdo.oliveira@gmail.com|Năo| 05/06/1995|Masculino|="971791755"|=""| 10/04/2019||=""|=""|||||||OBRIGADA PELA CONFIANÇA!!|
Maria margarete Carvalho Alves Cordeiro ||Năo| 12/09/1968|Feminino|=""|=""| 12/04/2019||=""|=""||||||||
Ricardo Santos Oliveira|richardolivermfk@bol.com.br|Năo| 26/03/1987|Masculino|="976887251"|=""| 17/04/2019||=""|=""||||||||
Michael Bonfim Barbosa |michael9027barbosa@gmail.com|Năo| 27/02/1990|Masculino|="96556-8550"|=""| 23/04/2019||=""|=""||||||||"""
# Salvar o CSV de teste
with open('data/pacientes_teste.csv', 'w', encoding='utf-8') as f:
    f.write(csv_teste)
print("✅ CSV de teste criado em data/pacientes_teste.csv (50 pacientes)")
